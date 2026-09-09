"""Development-only joint optimizer for the deterministic routing policy.

The optimizer searches only ``dev.csv`` and writes a frozen profile. It tunes
an automation threshold plus a small, interpretable evidence-confidence weight.
The held-out test set is never read here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import CONTEST_COST, MIN_EVIDENCE_COMPLETENESS

POLICY_PROFILE_PATH = ARTIFACTS_DIR / "policy_profile.json"


@dataclass(frozen=True)
class PolicyProfile:
    policy_version: str
    auto_contest_threshold: float
    accept_loss_threshold: float
    monetary_ceiling: float
    min_evidence_completeness: float
    contest_cost: float
    evidence_signal_weight: float
    model_threshold: float
    selection_split: str
    objective: str
    constraints: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    scorer = load_or_fit_ml_scorer()
    probabilities = []
    confidence = []
    eligible = []
    amounts = df["amount"].to_numpy(dtype=float)
    truth = df["would_win"].to_numpy(dtype=bool)
    for row in df.to_dict("records"):
        packet = assemble(row)
        quality = score_evidence(row, packet)
        probabilities.append(scorer.predict_win_probability(row))
        confidence.append(quality.confidence)
        eligible.append(quality.completeness >= MIN_EVIDENCE_COMPLETENESS and quality.validity >= 1.0)
    return np.asarray(probabilities), np.asarray(confidence), np.asarray(eligible), amounts, truth


def evaluate_candidate(
    probabilities: np.ndarray,
    confidence: np.ndarray,
    eligible: np.ndarray,
    amounts: np.ndarray,
    truth: np.ndarray,
    *,
    threshold: float,
    evidence_signal_weight: float,
) -> dict:
    routing_score = np.clip(
        probabilities + evidence_signal_weight * (confidence - 0.80),
        0.0,
        1.0,
    )
    auto = (routing_score >= threshold) & eligible & (amounts <= 50_000.0)
    idx = np.flatnonzero(auto)
    count = len(idx)
    tp = int(truth[idx].sum())
    precision = tp / count if count else 0.0
    total_positive = int(truth.sum())
    recall = tp / total_positive if total_positive else 0.0
    expected_recovery = float(np.sum(amounts[idx] * probabilities[idx]))
    realized_recovery = float(np.sum(amounts[idx][truth[idx]]))
    net_value = expected_recovery - count * CONTEST_COST
    realized_net = realized_recovery - count * CONTEST_COST
    return {
        "threshold": float(threshold),
        "evidence_signal_weight": float(evidence_signal_weight),
        "auto_contest_count": count,
        "auto_contest_rate": count / len(truth),
        "precision": precision,
        "recall": recall,
        "expected_recovery": expected_recovery,
        "expected_net_value": net_value,
        "realized_recovery": realized_recovery,
        "realized_net_value": realized_net,
        "false_positive_count": count - tp,
        "review_rate": 1.0 - count / len(truth),
    }



def evaluate_threshold(df: pd.DataFrame, probabilities: np.ndarray, threshold: float) -> dict:
    """Backward-compatible wrapper for threshold-only dev evaluation."""
    probabilities = np.asarray(probabilities, dtype=float)
    amounts = df["amount"].to_numpy(dtype=float)
    truth = df["would_win"].to_numpy(dtype=bool)
    auto = probabilities >= float(threshold)
    idx = np.flatnonzero(auto)
    tp = int(truth[idx].sum())
    precision = tp / len(idx) if len(idx) else 0.0
    recall = tp / int(truth.sum()) if truth.sum() else 0.0
    expected_recovery = float(np.sum(amounts[idx] * probabilities[idx]))
    return {
        "threshold": float(threshold),
        "auto_contest_count": int(len(idx)),
        "auto_contest_rate": float(len(idx) / len(df)),
        "precision": precision,
        "recall": recall,
        "expected_recovery": expected_recovery,
        "expected_net_value": expected_recovery - len(idx) * CONTEST_COST,
        "false_positive_count": int(len(idx) - tp),
        "review_rate": float(1.0 - len(idx) / len(df)),
    }

def optimize_policy(
    dev: pd.DataFrame | None = None,
    *,
    thresholds: list[float] | None = None,
    evidence_weights: list[float] | None = None,
    min_precision: float = 0.72,
    max_auto_rate: float = 0.40,
) -> tuple[PolicyProfile, list[dict]]:
    dev = dev if dev is not None else pd.read_csv(DATA_DIR / "dev.csv")
    thresholds = thresholds or [round(x, 3) for x in np.arange(0.55, 0.851, 0.005)]
    evidence_weights = evidence_weights or [round(x, 3) for x in np.arange(0.0, 0.151, 0.005)]
    probabilities, confidence, eligible, amounts, truth = _features(dev)

    candidates = [
        evaluate_candidate(
            probabilities, confidence, eligible, amounts, truth,
            threshold=t, evidence_signal_weight=w,
        )
        for w in evidence_weights for t in thresholds
    ]
    feasible = [
        c for c in candidates
        if c["precision"] >= min_precision and c["auto_contest_rate"] <= max_auto_rate
    ]
    if not feasible:
        # Fallback to the safest candidate among the full search space.
        feasible = sorted(candidates, key=lambda c: (c["precision"], -c["auto_contest_rate"]), reverse=True)[:1]

    best = max(
        feasible,
        key=lambda c: (c["expected_net_value"], c["precision"], c["recall"]),
    )
    profile = PolicyProfile(
        policy_version="policy-v6-dev-joint-optimized",
        auto_contest_threshold=best["threshold"],
        accept_loss_threshold=0.30,
        monetary_ceiling=50_000.0,
        min_evidence_completeness=MIN_EVIDENCE_COMPLETENESS,
        contest_cost=CONTEST_COST,
        evidence_signal_weight=best["evidence_signal_weight"],
        model_threshold=best["threshold"],
        selection_split="dev.csv only",
        objective="maximize expected net value subject to precision and automation-rate constraints",
        constraints={"min_precision": min_precision, "max_auto_rate": max_auto_rate},
    )
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    POLICY_PROFILE_PATH.write_text(json.dumps(profile.to_dict(), indent=2))
    return profile, candidates


def main() -> None:
    profile, candidates = optimize_policy()
    feasible = [c for c in candidates if c["precision"] >= profile.constraints["min_precision"] and c["auto_contest_rate"] <= profile.constraints["max_auto_rate"]]
    print(json.dumps({"profile": profile.to_dict(), "top_feasible_candidates": sorted(feasible, key=lambda x: x["expected_net_value"], reverse=True)[:10]}, indent=2))


if __name__ == "__main__":
    main()
