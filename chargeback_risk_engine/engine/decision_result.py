"""Canonical result object returned by every decision entry point."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CanonicalDecision:
    dispute_id: str
    reason_code: str
    amount: float
    action: str
    win_probability: float
    calibrated_win_probability: float
    evidence: list[dict[str, Any]]
    evidence_score: dict[str, Any]
    graph_analysis: dict[str, Any]
    economic_decision: dict[str, Any]
    reason: str
    expected_value: float
    explanation: dict[str, Any]
    counterfactual: dict[str, Any]
    replayed: bool
    contest_draft: dict[str, Any] | None
    audit_id: str | None
    model_version: str
    policy_version: str
    feature_version: str
    live_model: str
    challenger_models: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
