"""Optional Track 03-style bounded recovery planner."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RecoveryPlan:
    intervention: str
    expected_value: float
    max_attempts: int


def choose_plan(amount: float, success_probability: float, *, intervention_cost: float = 10.0) -> RecoveryPlan:
    p = min(1.0, max(0.0, float(success_probability)))
    expected_value = amount * p - intervention_cost
    if expected_value <= 0:
        return RecoveryPlan("NO_ACTION", expected_value, 0)
    if p >= 0.75:
        return RecoveryPlan("RETRY_PRIMARY", expected_value, 1)
    return RecoveryPlan("OFFER_FALLBACK", expected_value, 1)
