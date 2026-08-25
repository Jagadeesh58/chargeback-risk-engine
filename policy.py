"""
policy.py — deterministic policy engine. Takes a scorer's P(win) and
turns it into a routing decision. Per principle #6: the monetary safety
ceiling can NEVER be overridden by model confidence -- enforced here by
checking amount FIRST, unconditionally, before dispute_probability is
ever read.
"""

from dataclasses import dataclass

# --- Tunable policy parameters, all in one place for Checkpoint 7's
# sensitivity analysis later ---
MONETARY_CEILING = 50_000.0     # above this, ALWAYS human review, no exceptions
AUTO_CONTEST_THRESHOLD = 0.65   # P(win) above this -> auto-contest (if under ceiling)
ACCEPT_LOSS_THRESHOLD = 0.30    # P(win) below this -> accept loss (if under ceiling)
# between the two thresholds -> human review (genuinely ambiguous case)

CONTEST_COST = 150.0            # flat cost of assembling+filing evidence
RISK_COST_IF_LOSE_CONTEST = 0.0  # simplification: losing a contest doesn't add
                                  # extra penalty beyond the lost amount itself
                                  # (documented assumption, not invented silently)


@dataclass
class PolicyDecision:
    action: str                  # "AUTO-CONTEST" | "HUMAN REVIEW" | "ACCEPT LOSS"
    reason: str                  # human-readable justification
    expected_value: float        # EV of contesting, for transparency/logging


def compute_expected_value(win_probability: float, amount: float) -> float:
    """
    EV = P(win) * recoverable_amount - contest_cost - expected_risk_cost
    per principle #8. Assumptions stated explicitly above, not invented
    silently: contest cost is a flat fee, and we assume no extra penalty
    beyond the lost amount if a contest is lost.
    """
    return (
        win_probability * amount
        - CONTEST_COST
        - (1 - win_probability) * RISK_COST_IF_LOSE_CONTEST
    )


def decide(win_probability: float, amount: float) -> PolicyDecision:
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

    # --- STEP 2: only now do we look at the model's probability ---
    ev = compute_expected_value(win_probability, amount)

    if win_probability >= AUTO_CONTEST_THRESHOLD:
        return PolicyDecision(
            action="AUTO-CONTEST",
            reason=f"P(win)={win_probability:.2f} >= {AUTO_CONTEST_THRESHOLD}, "
                   f"under ceiling, EV={ev:.2f}.",
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