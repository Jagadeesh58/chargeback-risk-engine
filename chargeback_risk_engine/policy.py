"""
policy.py — deterministic policy engine. Takes a scorer's P(win) and
turns it into a routing decision. The monetary safety ceiling can NEVER
be overridden by model confidence -- enforced here by checking amount
FIRST, unconditionally, before dispute_probability is ever read.
"""

from dataclasses import dataclass

# --- Tunable policy parameters, all in one place so a later sensitivity
# analysis can sweep them without touching the decision logic ---
MONETARY_CEILING = 50_000.0     # above this, ALWAYS human review, no exceptions
AUTO_CONTEST_THRESHOLD = 0.65   # P(win) above this -> auto-contest (if under ceiling)
ACCEPT_LOSS_THRESHOLD = 0.30    # P(win) below this -> accept loss (if under ceiling)
# between the two thresholds -> human review (genuinely ambiguous case)

# A high P(win) can occur with very little CONFIRMED evidence, because
# None (unknown) is neutral rather than negative in the
# scorer. A dispute with 1 PASS out of 3 relevant fields can still clear
# AUTO_CONTEST_THRESHOLD. That's not safe to auto-submit -- we'd be
# contesting on mostly-unconfirmed evidence. This gate requires a MAJORITY
# of relevant evidence fields to be confirmed PASS before AUTO-CONTEST is
# allowed, regardless of how high the probability is.
MIN_PASS_FRACTION_FOR_AUTO_CONTEST = 0.5  # >50% of relevant fields must be PASS

CONTEST_COST = 150.0            # flat cost of assembling+filing evidence
RISK_COST_IF_LOSE_CONTEST = 0.0
MIN_MODEL_CONFIDENCE = 0.60
MAX_CONTEST_COUNT = 1
MIN_EVIDENCE_COMPLETENESS = 0.50
MAX_INVALID_EVIDENCE = 0
MAX_CONTRADICTORY_EVIDENCE = 0  # simplification: losing a contest doesn't add
                                  # extra penalty beyond the lost amount itself
                                  # (documented assumption, not invented silently)


@dataclass
class PolicyDecision:
    action: str                  # "AUTO-CONTEST" | "HUMAN REVIEW" | "ACCEPT LOSS"
    reason: str                  # human-readable justification
    expected_value: float        # EV of contesting, for transparency/logging


def compute_expected_value(win_probability: float, amount: float) -> float:
    """
    EV = P(win) * recoverable_amount - contest_cost - expected_risk_cost.
    Assumptions stated explicitly above, not invented silently: contest
    cost is a flat fee, and we assume no extra penalty beyond the lost
    amount if a contest is lost.
    """
    return (
        win_probability * amount
        - CONTEST_COST
        - (1 - win_probability) * RISK_COST_IF_LOSE_CONTEST
    )


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
) -> PolicyDecision:
    # --- STEP 1: monetary ceiling check. UNCONDITIONAL. This is the
    # very first thing that happens, and it never reads win_probability.
    # Nothing below this line can produce a different outcome for an
    # over-ceiling dispute. ---
    if amount > MONETARY_CEILING:
        return PolicyDecision(
            action="HUMAN REVIEW",
            reason=f"Amount {amount:.2f} exceeds monetary ceiling {MONETARY_CEILING:.2f} "
                   f"-- always routed to a human regardless of model confidence.",
            expected_value=compute_expected_value(win_probability, amount),
        )

    # --- STEP 2: compute economic value and enforce non-negotiable evidence gates ---
    ev = compute_expected_value(win_probability, amount)
    if expected_net_value is not None:
        ev = expected_net_value

    # Hard safety fallbacks stay deterministic and model-agnostic. Missing, invalid,
    # or contradictory evidence must never silently turn into ACCEPT LOSS or AUTO-CONTEST.
    if evidence_quality is not None:
        if evidence_quality.completeness < MIN_EVIDENCE_COMPLETENESS:
            return PolicyDecision(
                action="HUMAN REVIEW",
                reason=f"Evidence completeness {evidence_quality.completeness:.2f} is below required {MIN_EVIDENCE_COMPLETENESS:.2f}.",
                expected_value=ev,
            )
        invalid = sum(not item.valid for item in evidence_quality.items)
        contradictory = sum(not item.consistent for item in evidence_quality.items)
        if invalid > MAX_INVALID_EVIDENCE or contradictory > MAX_CONTRADICTORY_EVIDENCE:
            return PolicyDecision(
                action="HUMAN REVIEW",
                reason=f"Evidence quality failed: invalid={invalid}, contradictory={contradictory}.",
                expected_value=ev,
            )

    if graph_risk_score >= 0.60:
        return PolicyDecision(
            action="HUMAN REVIEW",
            reason=f"Relationship risk score {graph_risk_score:.2f} triggered manual-review safety escalation.",
            expected_value=ev,
        )

    if contest_count >= MAX_CONTEST_COUNT:
        return PolicyDecision(
            action="HUMAN REVIEW",
            reason=f"Contest count {contest_count} reached retry/contest limit {MAX_CONTEST_COUNT}.",
            expected_value=ev,
        )
    if not external_service_available:
        return PolicyDecision(
            action="HUMAN REVIEW",
            reason="Required external service is unavailable; safe manual fallback selected.",
            expected_value=ev,
        )

    if win_probability >= AUTO_CONTEST_THRESHOLD:
        if model_confidence is not None and model_confidence < MIN_MODEL_CONFIDENCE:
            return PolicyDecision(
                action="HUMAN REVIEW",
                reason=f"Model confidence {model_confidence:.2f} is below the minimum {MIN_MODEL_CONFIDENCE:.2f}.",
                expected_value=ev,
            )
        # --- STEP 2b: evidence-completeness gate. A high probability
        # alone is not enough -- we also need a majority of relevant
        # evidence to be CONFIRMED (PASS), not just "not contradicted".
        # If evidence_packet isn't provided, this gate is skipped (e.g.
        # for callers that only care about probability/ceiling behavior).
        if evidence_packet is not None and evidence_packet.total > 0:
            pass_fraction = evidence_packet.pass_count / evidence_packet.total
            if pass_fraction < MIN_PASS_FRACTION_FOR_AUTO_CONTEST:
                return PolicyDecision(
                    action="HUMAN REVIEW",
                    reason=f"P(win)={win_probability:.2f} clears the threshold, but only "
                           f"{evidence_packet.pass_count}/{evidence_packet.total} relevant "
                           f"fields are confirmed (PASS) -- below the "
                           f"{MIN_PASS_FRACTION_FOR_AUTO_CONTEST:.0%} confirmation bar "
                           f"required for auto-contest. EV={ev:.2f}.",
                    expected_value=ev,
                )
        if ev <= 0:
            return PolicyDecision(
                action="HUMAN REVIEW",
                reason=f"P(win)={win_probability:.2f} clears the threshold, but expected net value {ev:.2f} is not positive.",
                expected_value=ev,
            )
        return PolicyDecision(
            action="AUTO-CONTEST",
            reason=f"P(win)={win_probability:.2f} >= {AUTO_CONTEST_THRESHOLD}, "
                   f"under ceiling, evidence confirmed sufficiently, EV={ev:.2f}.",
            expected_value=ev,
        )
    elif win_probability <= ACCEPT_LOSS_THRESHOLD:
        return PolicyDecision(
            action="ACCEPT LOSS",
            reason=f"P(win)={win_probability:.2f} <= {ACCEPT_LOSS_THRESHOLD}, "
                   f"contesting not worthwhile, EV={ev:.2f}.",
            expected_value=ev,
        )
    else:
        return PolicyDecision(
            action="HUMAN REVIEW",
            reason=f"P(win)={win_probability:.2f} is ambiguous "
                   f"(between {ACCEPT_LOSS_THRESHOLD} and {AUTO_CONTEST_THRESHOLD}), EV={ev:.2f}.",
            expected_value=ev,
        )