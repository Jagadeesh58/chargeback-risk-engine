"""Deterministic drift monitor: detect, explain, and recommend; never auto-promote a model."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np


@dataclass(frozen=True)
class DriftSignal:
    feature: str
    baseline_mean: float
    current_mean: float
    standardized_shift: float
    status: str


@dataclass(frozen=True)
class DriftReport:
    status: str
    signals: list[DriftSignal]
    adaptation_action: str
    reason: str


def _safe_std(values: np.ndarray) -> float:
    std = float(np.std(values))
    return std if std > 1e-9 else 1.0


def detect_drift(
    baseline: dict[str, list[float]],
    current: dict[str, list[float]],
    *,
    warn_z: float = 2.0,
    adapt_z: float = 3.0,
) -> DriftReport:
    """Return a reviewable drift diagnosis.

    This component deliberately has no training, deployment, or execution authority.
    A sustained signal recommends recalibration/review; it never mutates the live model.
    """
    signals: list[DriftSignal] = []
    for feature in sorted(set(baseline) & set(current)):
        b = np.asarray(baseline[feature], dtype=float)
        c = np.asarray(current[feature], dtype=float)
        if len(b) == 0 or len(c) == 0:
            continue
        z = abs(float(np.mean(c) - np.mean(b))) / _safe_std(b)
        status = "ADAPTATION_CANDIDATE" if z >= adapt_z else "SHIFT_DETECTED" if z >= warn_z else "NORMAL"
        signals.append(DriftSignal(feature, float(np.mean(b)), float(np.mean(c)), z, status))

    max_z = max((s.standardized_shift for s in signals), default=0.0)
    if max_z >= adapt_z:
        return DriftReport(
            "ADAPTATION_CANDIDATE", signals,
            "HUMAN_REVIEW_AND_RECALIBRATION", 
            "A persistent material distribution shift should be validated on a fresh held-out window before promotion.",
        )
    if max_z >= warn_z:
        return DriftReport(
            "SHIFT_DETECTED", signals,
            "MONITOR_AND_GATHER_FRESH_LABELS",
            "Distribution shift is visible but below the automatic adaptation threshold.",
        )
    return DriftReport("NORMAL", signals, "CONTINUE_MONITORING", "No material mean shift detected.")


def to_dict(report: DriftReport) -> dict:
    return {
        "status": report.status,
        "signals": [asdict(s) for s in report.signals],
        "adaptation_action": report.adaptation_action,
        "reason": report.reason,
    }
