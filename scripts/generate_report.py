"""Generate reproducible evaluation, ablation, review-budget and audit artifacts."""
from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chargeback_risk_engine.baseline import run_naive_baseline
from chargeback_risk_engine.calibration import apply_calibration, load_or_fit_calibration_points
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import decide
from chargeback_risk_engine.review_budget import optimize_review_budget


def _row(row):
    d = row.to_dict()
    for k, v in d.items():
        if isinstance(v, float) and pd.isna(v): d[k] = None
    return d


def _risk_metrics(y, p):
    calibrated = [apply_calibration(load_or_fit_calibration_points(), float(v)) for v in p]
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "brier_score": float(brier_score_loss(y, p)),
        "calibrated_brier_score": float(brier_score_loss(y, calibrated)),
    }


def _actions(df, mode):
    ml = load_or_fit_ml_scorer()
    rule_predict = None
    if mode == "rules":
        from chargeback_risk_engine.scorer import predict_win_probability
        rule_predict = predict_win_probability
    graph = None
    if mode in {"graph", "full"}:
        from chargeback_risk_engine.engine.risk_graph import RiskGraph
        graph = RiskGraph()
    out = []
    for _, row in df.iterrows():
        d = _row(row); packet = assemble(d); quality = score_evidence(d, packet)
        p = rule_predict(d) if rule_predict else ml.predict_win_probability(d)
        ev = calculate_economic_value(d["amount"], p)
        graph_score = 0.0
        if graph is not None:
            graph_score = graph.analyze(d).risk_score
        kwargs = {"evidence_packet":packet, "evidence_quality":quality, "expected_net_value":ev.expected_net_value}
        if mode == "economics":
            kwargs["expected_net_value"] = calculate_economic_value(d["amount"], p, contest_cost=300.0).expected_net_value
        if mode in {"graph", "full"}:
            kwargs["graph_risk_score"] = graph_score
        out.append(decide(p, d["amount"], **kwargs).action)
    return out


def _ablation(df):
    rows = []
    for name, mode in [("Rules only", "rules"), ("Model only", "model"), ("Model + Evidence", "evidence"),
                       ("Model + Economics", "economics"), ("Model + Graph", "graph"), ("Full system", "full")]:
        actions = _actions(df, mode)
        auto = [i for i, a in enumerate(actions) if a == "AUTO-CONTEST"]
        tp = sum(bool(df.iloc[i]["would_win"]) for i in auto)
        fp = len(auto) - tp
        positives = int(df["would_win"].sum())
        precision = tp / len(auto) if auto else 0.0
        recall = tp / positives if positives else 0.0
        rows.append({"component": name, "auto_contest_count": len(auto), "precision": precision,
                     "recall": recall, "f1": 2*precision*recall/(precision+recall) if precision+recall else 0.0,
                     "false_positive_cost": fp * 150.0})
    return rows


def _latency():
    d = {"dispute_id":"LATENCY_REPORT","payment_id":"pay_latency","reason_code":"item_not_received","amount":2400.0,
         "has_tracking_number":True,"has_delivery_confirmation":True,"has_signature_confirmation":True}
    with tempfile.TemporaryDirectory(prefix="latency_report_") as t:
        db = str(Path(t)/"audit.db")
        decide_case({**d,"dispute_id":"warm"}, db_path=db, include_counterfactual=False)
        samples=[]
        for i in range(100):
            s=time.perf_counter_ns(); decide_case({**d,"dispute_id":f"L{i}"}, db_path=db, include_counterfactual=False); samples.append((time.perf_counter_ns()-s)/1e6)
    samples.sort()
    return {"runs":len(samples), "p50_ms":samples[int(len(samples)*.50)-1], "p95_ms":samples[int(len(samples)*.95)-1],
            "p99_ms":samples[int(len(samples)*.99)-1], "max_ms":max(samples), "method":"warm local process; unique dispute IDs"}


def _html(report):
    rows = []
    for strategy in report["baselines"]:
        rows.append("<tr>" + "".join(f"<td>{strategy.get(k,'')}</td>" for k in ["strategy","auto_contest_count","precision","recall","expected_net_value"]) + "</tr>")
    ab = "".join("<tr>" + "".join(f"<td>{r[k]}</td>" for k in ["component","auto_contest_count","precision","recall","false_positive_cost"]) + "</tr>" for r in report["ablation"])
    rb = "".join("<tr>" + "".join(f"<td>{r[k]}</td>" for k in ["review_budget","capacity","precision_at_budget","recall_at_budget","recovered_value"]) + "</tr>" for r in report["review_budget"])
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Chargeback Risk Engine Proof Report</title><style>body{{font-family:system-ui;max-width:1100px;margin:40px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%;margin:16px 0}}td,th{{border:1px solid #ddd;padding:7px;text-align:left}}</style></head><body><h1>Chargeback Risk Engine</h1><p>Track 02 — AI Risk Manager</p><h2>Dataset</h2><pre>{json.dumps(report['dataset'],indent=2)}</pre><h2>Baselines</h2><table><tr><th>Strategy</th><th>Auto</th><th>Precision</th><th>Recall</th><th>Expected net value</th></tr>{rows}</table><h2>Ablation</h2><table><tr><th>Component</th><th>Auto</th><th>Precision</th><th>Recall</th><th>FP cost</th></tr>{ab}</table><h2>Review budget</h2><table><tr><th>Budget</th><th>Capacity</th><th>Precision</th><th>Recall</th><th>Recovered value</th></tr>{rb}</table><h2>Risk & calibration</h2><pre>{json.dumps(report['risk_metrics'],indent=2)}</pre><h2>Latency</h2><pre>{json.dumps(report['latency'],indent=2)}</pre><h2>Security</h2><pre>{json.dumps(report['adversarial_tests'],indent=2)}</pre></body></html>"""


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    test = pd.read_csv(DATA_DIR/"test.csv")
    benchmark = json.loads((ARTIFACTS_DIR / "candidate_benchmark.json").read_text())
    if int(benchmark["dataset"]["test_rows"]) != len(test) or "case_results" not in benchmark:
        raise RuntimeError("Run scripts/benchmark.py before scripts/generate_report.py")
    result_df = pd.DataFrame(benchmark["case_results"])
    y=test["would_win"].astype(int).tolist(); p=result_df["p_win"].astype(float).tolist()
    auto=result_df["action"].tolist()
    auto_idx=[i for i,a in enumerate(auto) if a=="AUTO-CONTEST"]
    tp=sum(y[i] for i in auto_idx); fp=len(auto_idx)-tp; fn=sum(y)-tp
    candidate_benchmark = next(x for x in benchmark["strategies"] if x["strategy"] == "CHARGEBACK-RISK-ENGINE")
    baselines=[
        {"strategy":"ALWAYS-CONTEST", **run_naive_baseline(test)},
        {"strategy":"ALWAYS-ACCEPT","auto_contest_count":0,"precision":0.0,"recall":0.0,"expected_net_value":0.0},
        {"strategy":"CHARGEBACK-RISK-ENGINE","auto_contest_count":len(auto_idx),"precision":tp/len(auto_idx) if auto_idx else 0.0,
         "recall":tp/sum(y) if sum(y) else 0.0,"expected_net_value":float(candidate_benchmark["expected_net_value"]),
         "synthetic_false_positive_count":fp,"comparison_note":"Frozen baseline values are historical 900-row measurements; the scaled test is reported separately because the original pre-change source snapshot is not bundled."}
    ]
    ablation_test = test.head(min(500, len(test))).copy()
    report={"dataset":{"name":"bundled synthetic transaction/chargeback dataset","synthetic":True,"train_rows":len(pd.read_csv(DATA_DIR/"train.csv")),"dev_rows":len(pd.read_csv(DATA_DIR/"dev.csv")),"test_rows":len(test),"split":"seeded 2/3 train, 1/6 dev, 1/6 held-out test; final reporting only on test.csv","leakage_controls":["synthetic label is excluded from scorer inputs","calibration fit from dev.csv","test outcomes are not used for threshold fitting"]},
            "baselines":baselines,"risk_metrics":_risk_metrics(y,p),"ablation":_ablation(ablation_test),"ablation_test_rows":len(ablation_test),
            "review_budget":optimize_review_budget(result_df).to_dict(orient="records"),
            "adversarial_tests":{"prompt_injection":"covered by deterministic evidence analyst boundary","contradictory_evidence":"policy -> HUMAN-REVIEW","missing_evidence":"WARN -> HUMAN-REVIEW","malformed_input":"API validation -> 422","duplicate_requests":"SQLite idempotency","replay_requests":"original decision replayed","future_timestamp_manipulation":"timestamp fields are not trusted as outcome features","amount_manipulation":"API amount bounds + monetary ceiling","graph_manipulation":"relationship identifiers treated as data","llm_schema_failure":"deterministic fallback","llm_timeout":"deterministic fallback","llm_unavailable":"offline operation","policy_boundary":"deterministic policy tests","retry_abuse":"contest-count policy gate","money_limit_bypass":"monetary ceiling gate"},
            "latency":_latency(),"audit":{"durable":"SQLite","fields":["case ID","decision","policy version","model version","evidence status","economic values","graph signal","AI metadata","timestamp","request ID"],"integrity":"idempotency and immutable insert; no external submission performed"}}
    (ARTIFACTS_DIR/"verification_report.json").write_text(json.dumps(report,indent=2))
    (ARTIFACTS_DIR/"verification_report.html").write_text(_html(report))
    candidate = next(x for x in report["baselines"] if x["strategy"] == "CHARGEBACK-RISK-ENGINE")
    print(json.dumps({"files":["artifacts/verification_report.json","artifacts/verification_report.html"],"test_rows":len(test),"auto_contest_count":len(auto_idx)},indent=2))
if __name__ == "__main__": main()
