"""Fair held-out comparison of decision strategies."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.scorer import predict_win_probability
from chargeback_risk_engine.baseline import run_naive_baseline
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import decide

BASELINE_PATH = ARTIFACTS_DIR / "baseline_benchmark.json"


def _row_dispute(row):
    dispute = row.to_dict()
    for key, value in dispute.items():
        if isinstance(value, float) and pd.isna(value):
            dispute[key] = None
    return dispute


def _strategy_metrics(name, test, actions, probabilities, outcome_prior):
    auto = [i for i, action in enumerate(actions) if action == "AUTO-CONTEST"]
    actual_wins = sum(bool(test.iloc[i]["would_win"]) for i in auto)
    false_positives = len(auto) - actual_wins
    precision = actual_wins / len(auto) if auto else 0.0
    total_wins = int(test["would_win"].sum())
    recall = actual_wins / total_wins if total_wins else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    expected_recovery = 0.0
    for i in auto:
        amount = float(test.iloc[i]["amount"])
        probability = float(outcome_prior if probabilities[i] is None else probabilities[i])
        economic = calculate_economic_value(amount, probability)
        expected_recovery += economic.expected_recovery
    total_amount = float(test["amount"].sum())
    expected_loss = total_amount - expected_recovery
    contest_cost = len(auto) * 150.0
    expected_net_value = expected_recovery - contest_cost
    human = sum(action == "HUMAN-REVIEW" for action in actions)
    return {
        "strategy": name,
        "auto_contest_count": len(auto),
        "auto_contest_precision": precision,
        "auto_contest_recall": recall,
        "auto_contest_f1": f1,
        "human_review_rate": human / len(actions) if actions else 0.0,
        "expected_recovery": expected_recovery,
        "expected_loss": expected_loss,
        "expected_contest_cost": contest_cost,
        "expected_net_value": expected_net_value,
        "synthetic_false_positive_count": false_positives,
    }


def evaluate() -> dict:
    test = pd.read_csv(DATA_DIR / "test.csv")
    ml = load_or_fit_ml_scorer()
    baseline_current = json.loads(BASELINE_PATH.read_text())
    baseline_current["expected_loss"] = float(test["amount"].sum()) - float(baseline_current["expected_recovery"])
    baseline_current["expected_loss"] = float(test["amount"].sum()) - float(baseline_current["expected_recovery"])

    rows = [_row_dispute(row) for _, row in test.iterrows()]
    rule_probs = [predict_win_probability(row) for row in rows]
    logistic_probs = [ml.predict_win_probability(row) for row in rows]
    outcome_prior = float(pd.read_csv(DATA_DIR / "train.csv")["would_win"].mean())

    strategies = []
    strategies.append(_strategy_metrics(
        "ALWAYS-CONTEST", test, ["AUTO-CONTEST"] * len(test), [None] * len(test), outcome_prior
    ))
    strategies.append(_strategy_metrics(
        "ALWAYS-ACCEPT", test, ["ACCEPT-LOSS"] * len(test), [None] * len(test), outcome_prior
    ))

    rules_actions = []
    logistic_actions = []
    for row, p in zip(rows, rule_probs):
        packet = assemble(row)
        quality = score_evidence(row, packet)
        econ = calculate_economic_value(row["amount"], p)
        rules_actions.append(decide(p, row["amount"], evidence_packet=packet, evidence_quality=quality, expected_net_value=econ.expected_net_value).action)
    for row, p in zip(rows, logistic_probs):
        packet = assemble(row)
        quality = score_evidence(row, packet)
        econ = calculate_economic_value(row["amount"], p)
        logistic_actions.append(decide(p, row["amount"], evidence_packet=packet, evidence_quality=quality, expected_net_value=econ.expected_net_value).action)

    strategies.append(_strategy_metrics("RULES-ONLY", test, rules_actions, rule_probs, outcome_prior))
    strategies.append(_strategy_metrics("LOGISTIC-ONLY", test, logistic_actions, logistic_probs, outcome_prior))
    strategies.append(baseline_current)

    with tempfile.TemporaryDirectory(prefix="benchmark_") as tmp:
        candidate_results = []
        for row in rows:
            candidate_results.append(decide_case(row, db_path=str(Path(tmp) / "audit.db"), include_counterfactual=False))
    candidate_actions = [r["action"] for r in candidate_results]
    strategies.append(_strategy_metrics("CHARGEBACK-RISK-ENGINE", test, candidate_actions, logistic_probs, outcome_prior))
    case_results = [
        {
            "dispute_id": row["dispute_id"],
            "amount": float(row["amount"]),
            "would_win": bool(row["would_win"]),
            "p_win": float(logistic_probs[i]),
            "action": candidate_results[i]["action"],
            "expected_net_value": float(candidate_results[i]["economic_decision"]["expected_net_value"]),
            "pass_count": int(sum(item["status"] == "PASS" for item in candidate_results[i]["evidence"])),
            "evidence_total": int(len(candidate_results[i]["evidence"])),
        }
        for i, row in enumerate(rows)
    ]

    return {
        "dataset": {"test_rows": len(test), "synthetic": True, "outcome_prior_from_train": outcome_prior},
        "strategies": strategies,
        "case_results": case_results,
        "notes": {
            "expected_recovery": "modeled using each strategy's probability signal; ALWAYS strategies use the train-set outcome prior only as a neutral reference",
            "realized_financial_recovery": "not measured; would_win is synthetic benchmark ground truth",
            "baseline_current_engine": "frozen measurement captured before candidate changes",
        },
    }


def main():
    result = evaluate()
    print(json.dumps(result, indent=2))
    (ARTIFACTS_DIR / "candidate_benchmark.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
