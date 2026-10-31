"""
test_policy.py — real, runnable tests for policy.py. The ceiling test is
the single most important test in this project: it proves model
confidence can never override the monetary safety ceiling.
"""

import random

from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.policy import MONETARY_CEILING, compute_expected_value, decide


def test_ceiling_holds_even_at_maximum_confidence():
    """The core safety property: no matter how confident the model is,
    an over-ceiling dispute is NEVER auto-contested."""
    over_ceiling_amount = MONETARY_CEILING + 1.0
    for probability in [0.99, 0.999, 0.9999, 1.0]:
        decision = decide(win_probability=probability, amount=over_ceiling_amount)
        assert decision.action != "AUTO-CONTEST", (
            f"SAFETY VIOLATION: amount={over_ceiling_amount}, "
            f"probability={probability} produced {decision.action}"
        )
        assert decision.action == "HUMAN-REVIEW"


def test_ceiling_holds_across_random_fuzzing():
    """Fuzz test: random amounts and probabilities above the ceiling should
    NEVER produce AUTO-CONTEST, across many random combinations."""
    rng = random.Random(123)
    for _ in range(2000):
        amount = MONETARY_CEILING + rng.uniform(0.01, 5_000_000)
        probability = rng.uniform(0.0, 1.0)
        decision = decide(win_probability=probability, amount=amount)
        assert decision.action != "AUTO-CONTEST", (
            f"SAFETY VIOLATION: amount={amount}, probability={probability} "
            f"produced {decision.action}"
        )


def test_below_ceiling_high_confidence_without_evidence_requires_human_review():
    decision = decide(win_probability=0.95, amount=1000.0)
    assert decision.action == "HUMAN-REVIEW"


def test_below_ceiling_low_confidence_accepts_loss():
    decision = decide(win_probability=0.05, amount=1000.0)
    assert decision.action == "ACCEPT-LOSS"


def test_below_ceiling_ambiguous_goes_to_human_review():
    decision = decide(win_probability=0.5, amount=1000.0)
    assert decision.action == "HUMAN-REVIEW"


def test_exactly_at_ceiling_is_still_eligible_for_auto_decisioning():
    """Boundary check: the rule is 'exceeds', so an amount exactly AT the
    ceiling should NOT be forced to HUMAN-REVIEW by the ceiling rule."""
    packet = assemble(
        {
            "reason_code": "item_not_received",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        }
    )
    decision = decide(win_probability=0.95, amount=MONETARY_CEILING, evidence_packet=packet)
    from chargeback_risk_engine.engine.evidence_score import score_evidence

    quality = score_evidence(
        {
            "reason_code": "item_not_received",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        },
        packet,
    )
    decision = decide(
        win_probability=0.95,
        amount=MONETARY_CEILING,
        evidence_packet=packet,
        evidence_quality=quality,
        expected_net_value=1000,
    )
    assert decision.action == "AUTO-CONTEST"


def test_expected_value_formula():
    ev = compute_expected_value(win_probability=0.8, amount=1000.0)
    # EV = 0.8 * 1000 - 150 - 0.2*0 = 650.0
    assert abs(ev - 650.0) < 0.01


def test_high_probability_but_mostly_unconfirmed_evidence_blocks_auto_contest():
    """1 PASS out of 3 relevant fields can still produce P(win) >=
    threshold, but should NOT be eligible for AUTO-CONTEST once the
    evidence packet is factored in."""
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": None,
        "has_signature_confirmation": None,
    }
    packet = assemble(dispute)
    assert packet.pass_count == 1 and packet.total == 3  # sanity check on the setup

    decision = decide(win_probability=0.697, amount=2000, evidence_packet=packet)
    assert decision.action != "AUTO-CONTEST"
    assert decision.action == "HUMAN-REVIEW"


def test_majority_confirmed_evidence_allows_auto_contest():
    """Sanity check the gate isn't overly strict: majority-confirmed
    evidence with high probability should still auto-contest."""
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    packet = assemble(dispute)
    from chargeback_risk_engine.engine.evidence_score import score_evidence

    quality = score_evidence(dispute, packet)
    decision = decide(
        win_probability=0.9,
        amount=2000,
        evidence_packet=packet,
        evidence_quality=quality,
        expected_net_value=500,
    )
    assert decision.action == "AUTO-CONTEST"


def test_evidence_gate_never_overrides_the_ceiling():
    """Even with a perfect evidence packet, the monetary ceiling still
    wins -- evidence completeness augments the probability check, it
    never substitutes for the ceiling check."""
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    packet = assemble(dispute)
    decision = decide(win_probability=0.99, amount=MONETARY_CEILING + 1, evidence_packet=packet)
    assert decision.action == "HUMAN-REVIEW"


def test_low_probability_large_dispute_with_positive_ev_routes_to_human_review():
    """Even if routing score is below accept_loss_threshold (e.g. 0.25 <= 0.30),
    a large dispute amount (e.g. ₹40,000) yields positive EV (+₹9,850).
    The policy must NOT walk away (ACCEPT-LOSS), but route to HUMAN-REVIEW."""
    decision = decide(win_probability=0.25, amount=40_000.0)
    assert decision.action == "HUMAN-REVIEW"
    assert decision.expected_value == 9850.0
    assert "positive" in decision.reason


def test_monetary_bounds_and_policy_gates():
    """Verify behavior across monetary spectrum and ensure policy gates fire."""
    packet = assemble(
        {
            "reason_code": "item_not_received",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        }
    )
    from chargeback_risk_engine.engine.evidence_score import score_evidence

    quality = score_evidence(
        {
            "reason_code": "item_not_received",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        },
        packet,
    )

    # 1. Retry contest count limit gate
    d_count = decide(0.9, 2000, evidence_packet=packet, evidence_quality=quality, contest_count=1)
    assert d_count.action == "HUMAN-REVIEW"
    assert "retry/contest limit" in d_count.reason

    # 2. External service availability gate
    d_ext = decide(
        0.9,
        2000,
        evidence_packet=packet,
        evidence_quality=quality,
        external_service_available=False,
    )
    assert d_ext.action == "HUMAN-REVIEW"
    assert "Required external service is unavailable" in d_ext.reason

    # 3. Model confidence gate
    d_conf = decide(
        0.9, 2000, evidence_packet=packet, evidence_quality=quality, model_confidence=0.4
    )
    assert d_conf.action == "HUMAN-REVIEW"
    assert "below the minimum" in d_conf.reason

    # 4. Monetary bounds: sub-training, in-training, above training, exactly at ceiling, and extreme (₹100M)
    # Small amount (₹150 dispute, EV <= 0)
    d_small = decide(0.20, 150.0)
    assert d_small.action == "ACCEPT-LOSS"
    assert d_small.expected_value < 0

    # In-training amount (₹4000)
    d_mid = decide(0.9, 4000.0, evidence_packet=packet, evidence_quality=quality)
    assert d_mid.action == "AUTO-CONTEST"

    # Extreme amount (₹100,000,000)
    d_extreme = decide(0.99, 100_000_000.0, evidence_packet=packet, evidence_quality=quality)
    assert d_extreme.action == "HUMAN-REVIEW"
    assert "exceeds monetary ceiling" in d_extreme.reason
