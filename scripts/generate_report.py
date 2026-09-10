"""Generate a judge-facing, reproducible proof package for the risk engine."""
from __future__ import annotations

import json
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chargeback_risk_engine.baseline import run_naive_baseline
from chargeback_risk_engine.calibration import apply_calibration, load_or_fit_calibration_points
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import (
    ACCEPT_LOSS_THRESHOLD, AUTO_CONTEST_THRESHOLD, CONTEST_COST, GRAPH_HUMAN_REVIEW_THRESHOLD,
    MIN_EVIDENCE_COMPLETENESS, MONETARY_CEILING,
)
from chargeback_risk_engine.review_budget import optimize_review_budget
from chargeback_risk_engine.scorer import predict_win_probability


def _row(row):
    d = row.to_dict()
    for k, v in d.items():
        if isinstance(v, float) and pd.isna(v):
            d[k] = None
    return d


def _risk_metrics(y, p):
    calibrated = [apply_calibration(load_or_fit_calibration_points(), float(v)) for v in p]
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "brier_score": float(brier_score_loss(y, p)),
        "calibrated_brier_score": float(brier_score_loss(y, calibrated)),
    }


def _simulate_actions(df: pd.DataFrame, probabilities: np.ndarray, *, evidence=True, economics=True, graph=True, threshold: float = AUTO_CONTEST_THRESHOLD) -> list[str]:
    actions = []
    for row, p in zip(df.to_dict("records"), probabilities):
        packet = assemble(row)
        quality = score_evidence(row, packet)
        if evidence and (quality.completeness < MIN_EVIDENCE_COMPLETENESS or quality.validity < 1.0):
            actions.append("HUMAN-REVIEW"); continue
        graph_score = 0.0
        if graph:
            graph_score = float(row.get("evaluation_graph_risk", 0.0) or 0.0)
            if graph_score >= GRAPH_HUMAN_REVIEW_THRESHOLD:
                actions.append("HUMAN-REVIEW"); continue
        ev = calculate_economic_value(float(row["amount"]), float(p)) if economics else None
        if float(p) >= threshold:
            if economics and ev.expected_net_value <= 0:
                actions.append("HUMAN-REVIEW"); continue
            if evidence and packet.total and packet.pass_count / packet.total <= 0.50:
                actions.append("HUMAN-REVIEW"); continue
            actions.append("AUTO-CONTEST")
        elif float(p) <= ACCEPT_LOSS_THRESHOLD and (not economics or ev.expected_net_value < 0):
            actions.append("ACCEPT-LOSS")
        else:
            actions.append("HUMAN-REVIEW")
    return actions


def _ablation(df: pd.DataFrame) -> list[dict]:
    ml = load_or_fit_ml_scorer()
    rows = [_row(r) for _, r in df.iterrows()]
    model_p = np.asarray([ml.predict_win_probability(r) for r in rows])
    rule_p = np.asarray([predict_win_probability(r) for r in rows])
    variants = [
        ("Rules only", rule_p, False, False, False),
        ("Model only", model_p, False, False, False),
        ("Model + Evidence", model_p, True, False, False),
        ("Model + Economics", model_p, False, True, False),
        ("Model + Graph", model_p, False, False, True),
        ("Full system", model_p, True, True, True),
    ]
    out=[]
    positives=int(df["would_win"].sum())
    for name,p,evidence,economics,graph in variants:
        actions=_simulate_actions(df,p,evidence=evidence,economics=economics,graph=graph)
        auto=[i for i,a in enumerate(actions) if a=="AUTO-CONTEST"]
        tp=sum(bool(df.iloc[i]["would_win"]) for i in auto); fp=len(auto)-tp
        precision=tp/len(auto) if auto else 0.0; recall=tp/positives if positives else 0.0
        realized_recovery=float(df.iloc[auto].loc[df.iloc[auto]["would_win"]==True,"amount"].sum()) if auto else 0.0
        net=realized_recovery-len(auto)*CONTEST_COST
        out.append({"component":name,"auto_contest_count":len(auto),"precision":precision,"recall":recall,
                    "f1":2*precision*recall/(precision+recall) if precision+recall else 0.0,
                    "false_positive_cost":fp*CONTEST_COST,"realized_recovery":realized_recovery,"realized_net_value":net})
    return out


def _bootstrap_mean(values: np.ndarray, seed: int = 42, n: int = 1000) -> dict:
    rng=np.random.default_rng(seed); values=np.asarray(values,dtype=float)
    if len(values)==0:return {"mean":0.0,"low":0.0,"high":0.0,"n":0}
    means=np.array([rng.choice(values,size=len(values),replace=True).mean() for _ in range(n)])
    return {"mean":float(values.mean()),"low":float(np.quantile(means,0.025)),"high":float(np.quantile(means,0.975)),"n":int(len(values))}


def _reason_breakdown(test: pd.DataFrame, p: np.ndarray) -> list[dict]:
    rows=[]
    for reason,g in test.assign(_p=p).groupby("reason_code",sort=True):
        pred=g["_p"]>=AUTO_CONTEST_THRESHOLD; y=g["would_win"].astype(bool)
        tp=int((pred&y).sum()); fp=int((pred&~y).sum()); fn=int((~pred&y).sum())
        rows.append({"reason_code":reason,"count":len(g),"pr_auc":float(average_precision_score(y,g["_p"])),
                     "precision_at_threshold":tp/(tp+fp) if tp+fp else 0.0,"recall_at_threshold":tp/(tp+fn) if tp+fn else 0.0})
    return rows


def _latency():
    d={"dispute_id":"LATENCY_REPORT","payment_id":"pay_latency","reason_code":"item_not_received","amount":2400.0,
       "has_tracking_number":True,"has_delivery_confirmation":True,"has_signature_confirmation":True}
    with tempfile.TemporaryDirectory(prefix="latency_report_") as t:
        db=str(Path(t)/"audit.db"); decide_case({**d,"dispute_id":"warm"},db_path=db,include_counterfactual=False)
        samples=[]
        for i in range(120):
            s=time.perf_counter_ns(); decide_case({**d,"dispute_id":f"L{i}"},db_path=db,include_counterfactual=False); samples.append((time.perf_counter_ns()-s)/1e6)
    samples.sort()
    q=lambda x: samples[min(len(samples)-1,max(0,math.ceil(len(samples)*x)-1))]
    return {"runs":len(samples),"p50_ms":q(.50),"p95_ms":q(.95),"p99_ms":q(.99),"max_ms":max(samples),"method":"warm local process; unique dispute IDs"}


def _html(report):
    strategy_cols=["strategy","auto_contest_count","auto_contest_precision","auto_contest_recall","realized_net_value"]
    srows="".join("<tr>"+"".join(f"<td>{r.get(k,'')}</td>" for k in strategy_cols)+"</tr>" for r in report["baselines"])
    abrows="".join("<tr>"+"".join(f"<td>{r.get(k,'')}</td>" for k in ["component","auto_contest_count","precision","recall","realized_net_value"])+"</tr>" for r in report["ablation"])
    rrows="".join("<tr>"+"".join(f"<td>{r.get(k,'')}</td>" for k in ["review_budget","capacity","precision_at_budget","recall_at_budget","incremental_net_value"])+"</tr>" for r in report["review_budget"])
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Chargeback Risk Engine — Judge Proof</title><style>body{{font-family:system-ui;max-width:1180px;margin:32px auto;padding:0 18px;line-height:1.45}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}th,td{{border:1px solid #ddd;padding:7px;font-size:14px}}th{{text-align:left}}code,pre{{background:#f6f6f6;padding:4px}}.hero{{padding:18px;border:2px solid #222;border-radius:14px}}</style></head><body><div class='hero'><h1>Chargeback Risk Engine</h1><p><b>Track 02 — AI Risk Manager</b></p><p><b>Claim:</b> AI-assisted chargeback decisions where the model proposes evidence-weighted risk, economics quantifies value, and deterministic policy controls the final financial action.</p></div><h2>Held-out headline</h2><pre>{json.dumps(report['headline'],indent=2)}</pre><h2>Strategy comparison</h2><table><tr><th>Strategy</th><th>Auto</th><th>Precision</th><th>Recall</th><th>Realized net value</th></tr>{srows}</table><h2>True ablation</h2><table><tr><th>Variant</th><th>Auto</th><th>Precision</th><th>Recall</th><th>Realized net value</th></tr>{abrows}</table><h2>Analyst capacity</h2><table><tr><th>Budget</th><th>Capacity</th><th>Precision</th><th>Incremental recall</th><th>Incremental net value</th></tr>{rrows}</table><h2>Per reason</h2><pre>{json.dumps(report['per_reason'],indent=2)}</pre><h2>Risk/calibration</h2><pre>{json.dumps(report['risk_metrics'],indent=2)}</pre><h2>Uncertainty</h2><pre>{json.dumps(report['confidence_intervals'],indent=2)}</pre><h2>Latency</h2><pre>{json.dumps(report['latency'],indent=2)}</pre><h2>Hard cases</h2><pre>{json.dumps(report['hard_cases'],indent=2)}</pre><h2>Security boundaries</h2><pre>{json.dumps(report['security'],indent=2)}</pre><h2>Reproducibility contract</h2><pre>{json.dumps(report['reproducibility'],indent=2)}</pre></body></html>"""


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    test=pd.read_csv(DATA_DIR/"test.csv"); train=pd.read_csv(DATA_DIR/"train.csv")
    benchmark=json.loads((ARTIFACTS_DIR/"candidate_benchmark.json").read_text())
    result_df=pd.DataFrame(benchmark["case_results"])
    y=test["would_win"].astype(int).to_numpy(); p=result_df["p_win"].astype(float).to_numpy()
    candidate=next(x for x in benchmark["strategies"] if x["strategy"]=="CHARGEBACK-RISK-ENGINE")
    base=next(x for x in benchmark["strategies"] if x["strategy"]=="FROZEN-PRE-CHANGE")
    per_case_net=np.where((result_df["action"]=="AUTO-CONTEST") & (result_df["would_win"]==True),result_df["amount"],0.0) - np.where(result_df["action"]=="AUTO-CONTEST",CONTEST_COST,0.0)
    rb=optimize_review_budget(result_df).to_dict("records")
    hard=json.loads((ARTIFACTS_DIR/"hard_cases_report.json").read_text()) if (ARTIFACTS_DIR/"hard_cases_report.json").exists() else {"total":0,"passed":0}
    report={
      "dataset":{"name":"bundled synthetic dataset","synthetic":True,"train_rows":len(train),"dev_rows":len(pd.read_csv(DATA_DIR/"dev.csv")),"test_rows":len(test),"split":"train/dev/test; final report uses test.csv only","label":"would_win is synthetic ground truth and is never fed to the decision engine"},
      "headline":{"pr_auc":float(average_precision_score(y,p)),"auto_contest_precision":candidate["auto_contest_precision"],"auto_contest_recall":candidate["auto_contest_recall"],"realized_recovery":candidate["realized_recovery"],"realized_net_value":candidate["realized_net_value"],"realized_net_value_lift_vs_frozen":None,"p95_latency_ms":_latency()["p95_ms"],"hard_cases_passed":hard.get("passed",0),"hard_cases_total":hard.get("total",0)},
      "baselines":[next(x for x in benchmark["strategies"] if x["strategy"]==s) for s in ["ALWAYS-CONTEST","ALWAYS-ACCEPT","RULES-ONLY","LOGISTIC-ONLY","FROZEN-PRE-CHANGE","CHARGEBACK-RISK-ENGINE"]],
      "ablation":_ablation(test.head(min(1000,len(test))).copy()),
      "ablation_test_rows":min(1000,len(test)),
      "review_budget":rb,
      "risk_metrics":_risk_metrics(y,p),
      "per_reason":_reason_breakdown(test,p),
      "confidence_intervals": {"case_level_realized_net_value":_bootstrap_mean(per_case_net)},
      "latency":_latency(),
      "hard_cases":hard,
      "security":{"policy_authoritative":True,"monetary_ceiling":MONETARY_CEILING,"idempotency":True,"audit_integrity":"SHA-256 chained audit records","ai_can_execute_financial_action":False,"prompt_injection_boundary":"notes/evidence are untrusted data","external_ai_failure":"deterministic fallback"},
      "reproducibility":{"test_outcomes_used_for_threshold_selection":False,"calibration_split":"dev.csv","policy_threshold":AUTO_CONTEST_THRESHOLD,"accept_loss_threshold":ACCEPT_LOSS_THRESHOLD,"minimum_evidence_completeness":MIN_EVIDENCE_COMPLETENESS,"contest_cost":CONTEST_COST,"command":"make verify"},
      "comparison_notes":{"frozen_baseline":"historical repository artifact; realized net value is not comparable because the historical snapshot did not store realized outcomes","realized_value":"synthetic ground truth only; not a production recovery claim","graph_ablation":"tabular benchmark has no network identifiers, so graph stress testing is separately reported rather than invented as a lift"},
    }
    (ARTIFACTS_DIR/"verification_report.json").write_text(json.dumps(report,indent=2))
    (ARTIFACTS_DIR/"verification_report.html").write_text(_html(report))
    print(json.dumps({"headline":report["headline"],"files":["artifacts/verification_report.json","artifacts/verification_report.html"]},indent=2))

if __name__=="__main__":
    main()
