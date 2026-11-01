"""Robustness benchmark: evaluates policy stability under parameter perturbations,

label noise, and covariate shifts against the synthetic ground truth.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CHARGEBACK_ENV", "development")
os.environ.setdefault("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "1")

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chargeback_risk_engine.config import (
    ALL_EVIDENCE_FIELDS,
    REASON_CODES,
    RELEVANT_EVIDENCE_BY_REASON,
)
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR
from chargeback_risk_engine.policy import ACCEPT_LOSS, AUTO_CONTEST, HUMAN_REVIEW, decide
from chargeback_risk_engine.policy_profile import decision_score, load_policy_profile

OUTPUT_PATH = ARTIFACTS_DIR / "robustness_report.json"


def generate_scenario_cases(
    n: int = 500,
    seed: int = 42,
    hidden_legit_base_rate: float = 0.60,
    relevant_field_rate_if_legit: float = 0.78,
    relevant_field_rate_if_not_legit: float = 0.30,
    contradiction_rate: float = 0.08,
    missingness_rate: float = 0.15,
    label_noise_rate: float = 0.0,
    amount_multiplier_sigma: float = 0.0,
    reason_skew: str | None = None,
) -> list[dict]:
    rng = np.random.default_rng(seed)
    cases = []

    for i in range(n):
        if reason_skew:
            reason = reason_skew if rng.random() < 0.80 else rng.choice(REASON_CODES)
        else:
            reason = REASON_CODES[i % len(REASON_CODES)]

        relevant_fields = set(RELEVANT_EVIDENCE_BY_REASON[reason])
        hidden_legit = bool(rng.random() < hidden_legit_base_rate)
        would_win = bool(rng.random() < (0.82 if hidden_legit else 0.18))

        # Inject label noise
        if label_noise_rate > 0.0 and rng.random() < label_noise_rate:
            would_win = not would_win

        case = {
            "dispute_id": f"ROB_{i:05d}",
            "payment_id": f"pay_rob_{i:05d}",
            "reason_code": reason,
            "would_win": would_win,
        }

        # Generate evidence
        for field in ALL_EVIDENCE_FIELDS:
            if field in relevant_fields:
                p_true = (
                    relevant_field_rate_if_legit
                    if hidden_legit
                    else relevant_field_rate_if_not_legit
                )
                val = bool(rng.random() < p_true)
                if rng.random() < contradiction_rate:
                    val = not val
            else:
                val = bool(rng.random() < 0.50)

            if rng.random() < missingness_rate:
                val = None

            case[field] = val

        # Generate dispute amount
        base_amount = float(rng.uniform(1000.0, 5000.0))
        if amount_multiplier_sigma > 0.0:
            base_amount *= float(rng.lognormal(mean=0.3, sigma=amount_multiplier_sigma))
        case["amount"] = round(max(100.0, base_amount), 2)

        cases.append(case)

    return cases


def evaluate_cases(cases: list[dict], scorer, profile) -> dict:
    actions = []
    wins = []
    expected_values = []

    for case in cases:
        p = scorer.predict_win_probability(case)
        packet = assemble(case)
        q = score_evidence(case, packet)
        s = decision_score(p, q.confidence, evidence_signal_weight=profile.evidence_signal_weight)
        ev = p * float(case["amount"]) - 150.0

        decision = decide(
            p,
            float(case["amount"]),
            evidence_packet=packet,
            evidence_quality=q,
            expected_net_value=ev,
            decision_score=s,
            auto_contest_threshold=profile.auto_contest_threshold,
            accept_loss_threshold=profile.accept_loss_threshold,
            monetary_ceiling=profile.monetary_ceiling,
            min_evidence_completeness=profile.min_evidence_completeness,
        )

        actions.append(decision.action)
        wins.append(case["would_win"])
        if decision.action == AUTO_CONTEST:
            expected_values.append(decision.expected_value)

    actions_arr = np.array(actions)
    wins_arr = np.array(wins, dtype=bool)

    auto_mask = actions_arr == AUTO_CONTEST
    auto_count = int(auto_mask.sum())
    true_positives = int((auto_mask & wins_arr).sum())
    total_wins = int(wins_arr.sum())

    precision = round(true_positives / auto_count, 4) if auto_count > 0 else 0.0
    recall = round(true_positives / total_wins, 4) if total_wins > 0 else 0.0
    auto_rate = round(auto_count / len(cases), 4) if cases else 0.0
    review_count = int((actions_arr == HUMAN_REVIEW).sum())
    accept_loss_count = int((actions_arr == ACCEPT_LOSS).sum())

    return {
        "cases": len(cases),
        "auto_contest_count": auto_count,
        "human_review_count": review_count,
        "accept_loss_count": accept_loss_count,
        "auto_contest_rate": auto_rate,
        "human_review_rate": round(review_count / len(cases), 4),
        "accept_loss_rate": round(accept_loss_count / len(cases), 4),
        "precision": precision,
        "recall": recall,
        "expected_net_value": round(float(sum(expected_values)), 2),
    }


def run_robustness_benchmark(output_path: Path = OUTPUT_PATH, n_per_scenario: int = 500) -> dict:
    scorer = load_or_fit_ml_scorer()
    profile = load_policy_profile()

    scenario_configs = {
        "baseline": {},
        "missingness_low_5pct": {"missingness_rate": 0.05},
        "missingness_high_35pct": {"missingness_rate": 0.35},
        "contradiction_low_2pct": {"contradiction_rate": 0.02},
        "contradiction_high_20pct": {"contradiction_rate": 0.20},
        "field_rate_low_65pct": {"relevant_field_rate_if_legit": 0.65},
        "field_rate_high_90pct": {"relevant_field_rate_if_legit": 0.90},
        "base_rate_low_45pct": {"hidden_legit_base_rate": 0.45},
        "base_rate_high_75pct": {"hidden_legit_base_rate": 0.75},
        "label_noise_5pct": {"label_noise_rate": 0.05},
        "label_noise_10pct": {"label_noise_rate": 0.10},
        "label_noise_20pct": {"label_noise_rate": 0.20},
        "covariate_shift_amount": {"amount_multiplier_sigma": 0.75},
        "covariate_shift_reasons": {"reason_skew": "unauthorized_transaction"},
    }

    results = {}
    for name, kwargs in scenario_configs.items():
        cases = generate_scenario_cases(n=n_per_scenario, seed=42, **kwargs)
        results[name] = evaluate_cases(cases, scorer, profile)

    report = {
        "benchmark": "robustness_perturbation_sweep",
        "cases_per_scenario": n_per_scenario,
        "synthetic": True,
        "methodology_disclaimer": (
            "NOTICE: Results are synthetic and circular by construction. This benchmark evaluates "
            "the numerical stability and degradation behavior of the decision policy under artificial "
            "distributional shifts; it does not constitute empirical proof of performance on real payment traffic."
        ),
        "scenarios": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    return report


if __name__ == "__main__":
    report = run_robustness_benchmark()
    print(f"Robustness benchmark saved to {OUTPUT_PATH}")
    for name, metrics in report["scenarios"].items():
        print(
            f"  {name:30s} -> precision={metrics['precision']:.4f}, recall={metrics['recall']:.4f}, auto_rate={metrics['auto_contest_rate']:.4f}"
        )
