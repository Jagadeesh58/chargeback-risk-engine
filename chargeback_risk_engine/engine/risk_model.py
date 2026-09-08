"""Risk-model selection helpers.

The live risk signal is the reason-aware Logistic Regression scorer. Rules and
HGB remain available for offline comparison and evaluation only.
"""
from __future__ import annotations


def live_risk_probability(ml_scorer, dispute: dict) -> float:
    """Return the single canonical live risk estimate."""
    value = float(ml_scorer.predict_win_probability(dispute))
    return max(0.0, min(1.0, value))


def combine_probabilities(*, rules: float, logistic: float, tree: float, weights: dict[str, float] | None = None) -> float:
    """Retained for offline challenger evaluation; never used by live policy."""
    from chargeback_risk_engine.config import HYBRID_MODEL_WEIGHTS
    w = weights or HYBRID_MODEL_WEIGHTS
    total = float(w["rules"] + w["logistic"] + w["tree"])
    if total <= 0:
        raise ValueError("Model weights must sum to a positive value")
    probability = (
        float(rules) * w["rules"]
        + float(logistic) * w["logistic"]
        + float(tree) * w["tree"]
    ) / total
    return max(0.0, min(1.0, probability))
