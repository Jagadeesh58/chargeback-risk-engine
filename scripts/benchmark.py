"""Fast, auditable held-out benchmark for model-only vs full policy routing."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import ACCEPT_LOSS, AUTO_CONTEST, HUMAN_REVIEW, decide
from chargeback_risk_engine.policy_optimizer import optimize_policy
from chargeback_risk_engine.policy_profile import load_policy_profile, decision_score, PROFILE_PATH

CONTEST_COST = 150.0


def _rows(df: pd.DataFrame):
    for row in df.to_dict("records"):
        for key, value in list(row.items()):
            if isinstance(value, float) and pd.isna(value):
                row[key] = None
        yield row


def _metrics(name: str, test: pd.DataFrame, actions: list[str], probabilities: list[float]) -> dict:
    y = test["would_win"].astype(bool).to_numpy()
    amounts = test["amount"].astype(float).to_numpy()
    auto = np.asarray([a == AUTO_CONTEST for a in actions], dtype=bool)
    idx = np.flatnonzero(auto)
    tp = int(y[idx].sum())
    count = int(len(idx))
    precision = tp / count if count else 0.0
    recall = tp / int(y.sum()) if y.sum() else 0.0
    expected_recovery = float(np.sum(amounts[idx] * np.asarray(probabilities)[idx]))
    realized_recovery = float(np.sum(amounts[idx][y[idx]]))
    net = expected_recovery - count * CONTEST_COST
    realized_net = realized_recovery - count * CONTEST_COST
    return {
        "strategy": name,
        "auto_contest_count": count,
        "auto_contest_rate": count / len(test),
        "auto_contest_precision": precision,
        "auto_contest_recall": recall,
        "auto_contest_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "human_review_count": actions.count(HUMAN_REVIEW),
        "human_review_rate": actions.count(HUMAN_REVIEW) / len(actions),
        "accept_loss_count": actions.count(ACCEPT_LOSS),
        "expected_recovery": expected_recovery,
        "expected_net_value": net,
        "realized_recovery": realized_recovery,
        "realized_net_value": realized_net,
        "false_positive_count": count - tp,
    }


def _optimize_model_only(dev: pd.DataFrame, scorer, min_precision: float = 0.72, max_auto_rate: float = 0.40) -> float:
    probs = np.asarray([scorer.predict_win_probability(r) for r in _rows(dev)])
    y = dev["would_win"].astype(bool).to_numpy()
    amounts = dev["amount"].astype(float).to_numpy()
    best = None
    for threshold in np.arange(0.55, 0.851, 0.005):
        auto = probs >= threshold
        idx = np.flatnonzero(auto)
        if len(idx) == 0 or len(idx) / len(dev) > max_auto_rate:
            continue
        precision = float(y[idx].sum()) / len(idx)
        if precision < min_precision:
            continue
        net = float(np.sum(amounts[idx] * probs[idx]) - len(idx) * CONTEST_COST)
        candidate = (net, precision, threshold)
        if best is None or candidate > best:
            best = candidate
    return float(best[2] if best else 0.65)


def review_frontier(test: pd.DataFrame, probabilities: np.ndarray) -> list[dict]:
    """Show capacity-aware top-k automation without changing the production policy."""
    order = np.argsort(-probabilities)
    y = test["would_win"].astype(bool).to_numpy()
    amounts = test["amount"].astype(float).to_numpy()
    rows = []
    for rate in (0.01, 0.02, 0.05, 0.10, 0.20):
        k = max(1, int(len(test) * rate))
        idx = order[:k]
        tp = int(y[idx].sum())
        rows.append({
            "capacity_rate": rate,
            "auto_count": k,
            "precision": tp / k,
            "recall": tp / int(y.sum()),
            "realized_net_value": float(np.sum(amounts[idx][y[idx]]) - k * CONTEST_COST),
        })
    return rows


def evaluate() -> dict:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    train = pd.read_csv(DATA_DIR / "train.csv")
    dev = pd.read_csv(DATA_DIR / "dev.csv")
    test = pd.read_csv(DATA_DIR / "test.csv")
    scorer = load_or_fit_ml_scorer()
    if not PROFILE_PATH.exists():
        optimize_policy(dev)
    profile = load_policy_profile()

    rows = list(_rows(test))
    probabilities = np.asarray([scorer.predict_win_probability(r) for r in rows])
    model_threshold = _optimize_model_only(dev, scorer)

    model_actions = [AUTO_CONTEST if p >= model_threshold else ACCEPT_LOSS for p in probabilities]
    full_actions = []
    routing_scores = []
    for row, p in zip(rows, probabilities):
        packet = assemble(row)
        quality = score_evidence(row, packet)
        score = decision_score(p, quality.confidence, evidence_signal_weight=profile.evidence_signal_weight)
        routing_scores.append(score)
        d = decide(
            p, row["amount"], evidence_packet=packet, evidence_quality=quality,
            expected_net_value=p * float(row["amount"]) - CONTEST_COST,
            decision_score=score,
            auto_contest_threshold=profile.auto_contest_threshold,
            accept_loss_threshold=profile.accept_loss_threshold,
            monetary_ceiling=profile.monetary_ceiling,
            min_evidence_completeness=profile.min_evidence_completeness,
        )
        full_actions.append(d.action)

    strategies = [
        _metrics("LOGISTIC-ONLY-DEV-OPTIMIZED", test, model_actions, probabilities.tolist()),
        _metrics("CHARGEBACK-RISK-ENGINE-FULL", test, full_actions, probabilities.tolist()),
    ]
    base, candidate = strategies
    candidate["incremental_vs_model_only"] = {
        "delta_expected_net_value": candidate["expected_net_value"] - base["expected_net_value"],
        "delta_realized_net_value": candidate["realized_net_value"] - base["realized_net_value"],
        "delta_precision": candidate["auto_contest_precision"] - base["auto_contest_precision"],
        "delta_recall": candidate["auto_contest_recall"] - base["auto_contest_recall"],
        "delta_auto_contest_rate": candidate["auto_contest_rate"] - base["auto_contest_rate"],
    }

    case_results = [
        {"dispute_id": row["dispute_id"], "reason_code": row["reason_code"], "amount": float(row["amount"]),
         "would_win": bool(row["would_win"]), "p_win": float(p), "routing_score": float(s), "action": action}
        for row, p, s, action in zip(rows, probabilities, routing_scores, full_actions)
    ]
    result = {
        "dataset": {
            "train_rows": len(train), "dev_rows": len(dev), "test_rows": len(test),
            "synthetic": True,
            "policy_selection_split": "dev.csv only",
            "no_test_tuning": True,
        },
        "policy_profile": asdict(profile),
        "model_only_threshold": model_threshold,
        "strategies": strategies,
        "case_results": case_results,
        "review_budget_frontier": review_frontier(test, probabilities),
        "routing_score_summary": {
            "min": float(np.min(routing_scores)),
            "median": float(np.median(routing_scores)),
            "max": float(np.max(routing_scores)),
        },
        "notes": {
            "model_only": "Pure thresholding of the live model probability; no evidence or policy gates.",
            "full_system": "Same frozen model plus deterministic evidence eligibility and a transparent evidence-confidence routing adjustment.",
            "business_metric": "Expected and realized net recovery are reported separately.",
            "honesty": "This is a synthetic held-out benchmark; no production-performance claim is made.",
        },
    }
    return result


def main() -> None:
    result = evaluate()
    (ARTIFACTS_DIR / "candidate_benchmark.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
