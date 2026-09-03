"""Transparent hybrid risk recommendation layer.

AI proposes a risk probability; this module never selects a financial action.
"""
from __future__ import annotations

from chargeback_risk_engine.config import HYBRID_MODEL_WEIGHTS


def combine_probabilities(*, rules: float, logistic: float, tree: float, weights: dict[str, float] | None = None) -> float:
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
