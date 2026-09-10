"""Deterministic final policy authority for chargeback routing."""
from __future__ import annotations

import math
from dataclasses import dataclass

from chargeback_risk_engine.engine.economic_decision import calculate_economic_value

MONETARY_CEILING = 50_000.0
AUTO_CONTEST_THRESHOLD = 0.65
ACCEPT_LOSS_THRESHOLD = 0.30
MIN_PASS_FRACTION_FOR_AUTO_CONTEST = 0.5
CONTEST_COST = 150.0
MIN_MODEL_CONFIDENCE = 0.60
MAX_CONTEST_COUNT = 1
MIN_EVIDENCE_COMPLETENESS = 0.50
MAX_INVALID_EVIDENCE = 0
MAX_CONTRADICTORY_EVIDENCE = 0
GRAPH_HUMAN_REVIEW_THRESHOLD = 0.60

AUTO_CONTEST = "AUTO-CONTEST"
HUMAN_REVIEW = "HUMAN-REVIEW"
ACCEPT_LOSS = "ACCEPT-LOSS"


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str
    expected_value: float


def compute_expected_value(win_probability: float, amount: float) -> float:
    """Compatibility helper backed by the canonical economic calculation."""
    return calculate_economic_value(
        amount,
        win_probability,
        contest_cost=CONTEST_COST,
    ).expected_net_value


def decide(
    win_probability: float,
    amount: float,
    evidence_packet=None,
    *,
    model_confidence: float | None = None,
    expected_net_value: float | None = None,
    contest_count: int = 0,
    external_service_available: bool = True,
    evidence_quality=None,
    graph_risk_score: float = 0.0,
    auto_contest_threshold: float = AUTO_CONTEST_THRESHOLD,
    accept_loss_threshold: float = ACCEPT_LOSS_THRESHOLD,
    monetary_ceiling: float = MONETARY_CEILING,
    decision_score: float | None = None,
    min_evidence_completeness: float = MIN_EVIDENCE_COMPLETENESS,
) -> PolicyDecision:
    """Apply safety, evidence, graph, economics and risk gates in fixed order."""
    if not math.isfinite(float(amount)) or float(amount) <= 0:
        return PolicyDecision(HUMAN_REVIEW, "Invalid dispute amount; manual review required.", 0.0)
    if not math.isfinite(float(win_probability)) or not 0.0 <= float(win_probability) <= 1.0:
        return PolicyDecision(HUMAN_REVIEW, "Invalid risk estimate; manual review required.", 0.0)
    if not math.isfinite(float(graph_risk_score)) or not 0.0 <= float(graph_risk_score) <= 1.0:
        return PolicyDecision(HUMAN_REVIEW, "Invalid relationship risk score; manual review required.", 0.0)

    if amount > float(monetary_ceiling):
        return PolicyDecision(
            HUMAN_REVIEW,
            f"Amount {amount:.2f} exceeds monetary ceiling {float(monetary_ceiling):.2f}; automatic contest is not allowed.",
            compute_expected_value(win_probability, amount),
        )

    ev = compute_expected_value(win_probability, amount)

    policy_score = float(win_probability if decision_score is None else decision_score)
    if not math.isfinite(policy_score) or not 0.0 <= policy_score <= 1.0:
        return PolicyDecision(HUMAN_REVIEW, "Invalid deterministic routing score; manual review required.", ev)

    if evidence_quality is not None:
        if evidence_quality.completeness < float(min_evidence_completeness):
            return PolicyDecision(
                HUMAN_REVIEW,
                f"Evidence completeness {evidence_quality.completeness:.2f} is below required {float(min_evidence_completeness):.2f}.",
                ev,
            )
        invalid = sum(not item.valid for item in evidence_quality.items)
        contradictory = sum(not item.consistent for item in evidence_quality.items)
        if invalid > MAX_INVALID_EVIDENCE or contradictory > MAX_CONTRADICTORY_EVIDENCE:
            return PolicyDecision(
                HUMAN_REVIEW,
                f"Evidence quality failed: invalid={invalid}, contradictory={contradictory}.",
                ev,
            )

    if graph_risk_score >= GRAPH_HUMAN_REVIEW_THRESHOLD:
        return PolicyDecision(
            HUMAN_REVIEW,
            f"Relationship risk score {graph_risk_score:.2f} triggered manual-review safety escalation.",
            ev,
        )

    if contest_count >= MAX_CONTEST_COUNT:
        return PolicyDecision(
            HUMAN_REVIEW,
            f"Contest count {contest_count} reached retry/contest limit {MAX_CONTEST_COUNT}.",
            ev,
        )
    if not external_service_available:
        return PolicyDecision(
            HUMAN_REVIEW,
            "Required external service is unavailable; safe manual fallback selected.",
            ev,
        )

    if policy_score >= float(auto_contest_threshold):
        if evidence_packet is None or evidence_quality is None:
            return PolicyDecision(
                HUMAN_REVIEW,
                "Win probability is high, but the canonical evidence evaluation was not supplied; automatic contest is not allowed.",
                ev,
            )
        if model_confidence is not None and float(model_confidence) < MIN_MODEL_CONFIDENCE:
            return PolicyDecision(
                HUMAN_REVIEW,
                f"Model confidence {model_confidence:.2f} is below the minimum {MIN_MODEL_CONFIDENCE:.2f}.",
                ev,
            )
        if evidence_packet is not None and evidence_packet.total > 0:
            pass_fraction = evidence_packet.pass_count / evidence_packet.total
            if pass_fraction <= MIN_PASS_FRACTION_FOR_AUTO_CONTEST:
                return PolicyDecision(
                    HUMAN_REVIEW,
                    f"Win probability clears the threshold, but only {evidence_packet.pass_count}/{evidence_packet.total} relevant fields are confirmed; the {MIN_PASS_FRACTION_FOR_AUTO_CONTEST:.0%} confirmation bar is not met.",
                    ev,
                )
        if ev <= 0:
            return PolicyDecision(
                HUMAN_REVIEW,
                f"Win probability clears the threshold, but expected net value {ev:.2f} is not positive.",
                ev,
            )
        return PolicyDecision(
            AUTO_CONTEST,
            f"Routing score {policy_score:.2f} >= {float(auto_contest_threshold):.2f}; calibrated win probability is {win_probability:.2f}, evidence is sufficiently confirmed, and expected net value is {ev:.2f}.",
            ev,
        )

    if policy_score <= float(accept_loss_threshold):
        return PolicyDecision(
            ACCEPT_LOSS,
            f"Routing score {policy_score:.2f} <= {float(accept_loss_threshold):.2f}; contesting is not worthwhile at the configured threshold.",
            ev,
        )

    return PolicyDecision(
        HUMAN_REVIEW,
        f"Routing score {policy_score:.2f} is ambiguous between {float(accept_loss_threshold):.2f} and {float(auto_contest_threshold):.2f}.",
        ev,
    )
