"""Load the frozen development-only policy profile at runtime.

The profile is an input to the deterministic policy layer, never to the model.
If the artifact is missing or malformed, safe defaults are used.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from chargeback_risk_engine.paths import ARTIFACTS_DIR

PROFILE_PATH = Path(ARTIFACTS_DIR) / "policy_profile.json"


@dataclass(frozen=True)
class RuntimePolicyProfile:
    auto_contest_threshold: float = 0.65
    accept_loss_threshold: float = 0.30
    monetary_ceiling: float = 50_000.0
    min_evidence_completeness: float = 0.50
    evidence_signal_weight: float = 0.05
    model_threshold: float = 0.65
    profile_version: str = "fallback"


def load_policy_profile(path: str | Path = PROFILE_PATH) -> RuntimePolicyProfile:
    """Load a validated profile; fall back safely on missing/corrupt artifacts."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text())
        return RuntimePolicyProfile(
            auto_contest_threshold=float(raw.get("auto_contest_threshold", 0.65)),
            accept_loss_threshold=float(raw.get("accept_loss_threshold", 0.30)),
            monetary_ceiling=float(raw.get("monetary_ceiling", 50_000.0)),
            min_evidence_completeness=float(raw.get("min_evidence_completeness", 0.50)),
            evidence_signal_weight=float(raw.get("evidence_signal_weight", 0.05)),
            model_threshold=float(raw.get("model_threshold", raw.get("auto_contest_threshold", 0.65))),
            profile_version=str(raw.get("policy_version", "loaded")),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return RuntimePolicyProfile()


def decision_score(
    win_probability: float,
    evidence_confidence: float,
    *,
    evidence_signal_weight: float | None = None,
) -> float:
    """Produce a conservative routing score distinct from calibrated probability.

    Missing/low-confidence evidence nudges automation downward without relabeling
    the underlying model probability. The deterministic policy remains the final
    authority.
    """
    profile = load_policy_profile()
    weight = profile.evidence_signal_weight if evidence_signal_weight is None else float(evidence_signal_weight)
    score = float(win_probability) + weight * (float(evidence_confidence) - 0.80)
    return max(0.0, min(1.0, score))
