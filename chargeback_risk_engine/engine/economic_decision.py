"""Business-value decision support for chargeback intervention."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EconomicDecision:
    disputed_amount: float
    probability_of_success: float
    recoverable_amount: float
    contest_cost: float
    operational_cost: float
    human_review_cost: float
    expected_recovery: float
    expected_cost: float
    expected_net_value: float
    recommended_action: str

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_economic_value(
    amount: float,
    probability_of_success: float,
    *,
    recoverable_fraction: float = 1.0,
    contest_cost: float = 150.0,
    operational_cost: float = 0.0,
    human_review_cost: float = 50.0,
    min_positive_net_value: float = 0.0,
) -> EconomicDecision:
    amount = max(0.0, float(amount))
    probability_of_success = min(1.0, max(0.0, float(probability_of_success)))
    recoverable_fraction = min(1.0, max(0.0, float(recoverable_fraction)))
    recoverable_amount = amount * recoverable_fraction
    expected_recovery = probability_of_success * recoverable_amount
    expected_cost = float(contest_cost) + float(operational_cost)
    net = expected_recovery - expected_cost
    action = "AUTO_CONTEST" if net > min_positive_net_value else "NO_ACTION"
    return EconomicDecision(
        disputed_amount=amount,
        probability_of_success=probability_of_success,
        recoverable_amount=recoverable_amount,
        contest_cost=float(contest_cost),
        operational_cost=float(operational_cost),
        human_review_cost=float(human_review_cost),
        expected_recovery=expected_recovery,
        expected_cost=expected_cost,
        expected_net_value=net,
        recommended_action=action,
    )
