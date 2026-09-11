"""Fair held-out comparison of risk strategies and realized economics."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from chargeback_risk_engine.baseline import run_naive_baseline
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import decide
from chargeback_risk_engine.policy_profile import load_policy_profile
from chargeback_risk_engine.engine.risk_graph import RiskGraph
from chargeback_risk_engine.scorer import predict_win_probability

BASELINE_PATH = ARTIFACTS_DIR / "baseline_benchmark.json"
CONTEST_COST = 150.0
REVIEW_COST = 50.0


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
    realized_recovery = 0.0
    for i in auto:
        amount = float(test.iloc[i]["amount"])
        probability = float(outcome_prior if probabilities[i] is None else probabilities[i])
        expected_recovery += calculate_economic_value(amount, probability).expected_recovery
        if bool(test.iloc[i]["would_win"]):
            realized_recovery += amount
    total_amount = float(test["amount"].sum())
    expected_net_value = expected_recovery - len(auto) * CONTEST_COST
    realized_net_value = realized_recovery - len(auto) * CONTEST_COST
    human = sum(action == "HUMAN-REVIEW" for action in actions)
    review_cost = human * REVIEW_COST
    return {
        "strategy": name,
        "auto_contest_count": len(auto),
        "auto_contest_precision": precision,
        "auto_contest_recall": recall,
        "auto_contest_f1": f1,
        "human_review_count": human,
        "human_review_rate": human / len(actions) if actions else 0.0,
        "expected_recovery": expected_recovery,
        "expected_loss": total_amount - expected_recovery,
        "expected_contest_cost": len(auto) * CONTEST_COST,
        "expected_review_cost": review_cost,
        "expected_net_value": expected_net_value,
        "realized_recovery": realized_recovery,
        "realized_net_value": realized_net_value,
        "synthetic_false_positive_count": false_positives,
    }


def evaluate() -> dict:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    test = pd.read_csv(DATA_DIR / "test.csv")
    train = pd.read_csv(DATA_DIR / "train.csv")
    ml = load_or_fit_ml_scorer()
    profile = load_policy_profile()
    baseline = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else None
    rows = [_row_dispute(row) for _, row in test.iterrows()]
    rule_probs = [predict_win_probability(row) for row in rows]
    logistic_probs = [ml.predict_win_probability(row) for row in rows]
    outcome_prior = float(train["would_win"].mean())

    always_contest = ["AUTO-CONTEST"] * len(test)
    always_accept = ["ACCEPT-LOSS"] * len(test)
    rules_actions, logistic_actions = [], []
    for row, p in zip(rows, rule_probs):
        packet = assemble(row); quality = score_evidence(row, packet)
        econ = calculate_economic_value(row["amount"], p)
        rules_actions.append(
            decide(
                p,
                row["amount"],
                evidence_packet=packet,
                evidence_quality=quality,
                expected_net_value=econ.expected_net_value,
                auto_contest_threshold=profile.auto_contest_threshold,
                accept_loss_threshold=profile.accept_loss_threshold,
                monetary_ceiling=profile.monetary_ceiling,
                min_evidence_completeness=profile.min_evidence_completeness,
            ).action
        )
    for row, p in zip(rows, logistic_probs):
        packet = assemble(row); quality = score_evidence(row, packet)
        econ = calculate_economic_value(row["amount"], p)
        logistic_actions.append(
            decide(
                p,
                row["amount"],
                evidence_packet=packet,
                evidence_quality=quality,
                expected_net_value=econ.expected_net_value,
                auto_contest_threshold=profile.auto_contest_threshold,
                accept_loss_threshold=profile.accept_loss_threshold,
                monetary_ceiling=profile.monetary_ceiling,
                min_evidence_completeness=profile.min_evidence_completeness,
            ).action
        )

    # Reuse one in-memory relationship graph during the benchmark instead of
    # rereading an ever-growing SQLite graph history for every test row.
    # The graph is updated incrementally in the same order as the held-out set.
    with tempfile.TemporaryDirectory(prefix="benchmark_") as tmp:
        db_path = str(Path(tmp) / "audit.db")
        benchmark_graph = RiskGraph()
        candidate_results = [
            decide_case(
                row,
                risk_graph=benchmark_graph,
                db_path=db_path,
                include_counterfactual=False,
            )
            for row in rows
        ]
    candidate_actions = [r["action"] for r in candidate_results]

    strategies = [
        _strategy_metrics("ALWAYS-CONTEST", test, always_contest, [None] * len(test), outcome_prior),
        _strategy_metrics("ALWAYS-ACCEPT", test, always_accept, [None] * len(test), outcome_prior),
        _strategy_metrics("RULES-ONLY", test, rules_actions, rule_probs, outcome_prior),
        _strategy_metrics("LOGISTIC-ONLY", test, logistic_actions, logistic_probs, outcome_prior),
        *([ {**baseline, "strategy": "FROZEN-PRE-CHANGE"} ] if baseline is not None else []),
        _strategy_metrics("CHARGEBACK-RISK-ENGINE", test, candidate_actions, logistic_probs, outcome_prior),
    ]

    case_results = []
    for i, row in enumerate(rows):
        result = candidate_results[i]
        case_results.append({
            "dispute_id": row["dispute_id"], "reason_code": row["reason_code"], "amount": float(row["amount"]),
            "would_win": bool(row["would_win"]), "p_win": float(logistic_probs[i]), "action": result["action"],
            "expected_net_value": float(result["economic_decision"]["expected_net_value"]),
            "expected_recovery": float(result["economic_decision"]["expected_recovery"]),
            "pass_count": int(sum(item["status"] == "PASS" for item in result["evidence"])),
            "evidence_total": int(len(result["evidence"])),
        })

    result = {
        "dataset": {"test_rows": len(test), "synthetic": True, "train_rows": len(train), "outcome_prior_from_train": outcome_prior},
        "strategies": strategies,
        "case_results": case_results,
        "notes": {
            "expected_recovery": "Expected recovery uses the strategy probability signal.",
            "realized_recovery": "Realized recovery is the sum of amount for AUTO-CONTEST cases where would_win=True; this is synthetic ground truth only.",
            "test_integrity": "No test outcomes are used to fit the model or tune the selected policy threshold.",
            "policy_profile": {
                "policy_version": profile.profile_version,
                "auto_contest_threshold": profile.auto_contest_threshold,
                "accept_loss_threshold": profile.accept_loss_threshold,
                "selection_source": "artifacts/policy_profile.json",
            },
            "frozen_baseline": (
                "Included from the versioned historical artifact."
                if baseline is not None
                else "Not included; historical baseline artifact is unavailable."
            ),
        },
    }
    return result


def main():
    result = evaluate()
    print(json.dumps(result, indent=2))
    (ARTIFACTS_DIR / "candidate_benchmark.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
