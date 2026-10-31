"""Strict mutation boundary and fail-closed tests for policy.decide."""

from __future__ import annotations

from dataclasses import dataclass

from chargeback_risk_engine.policy import (
    ACCEPT_LOSS,
    ACCEPT_LOSS_THRESHOLD,
    AUTO_CONTEST,
    AUTO_CONTEST_THRESHOLD,
    GRAPH_HUMAN_REVIEW_THRESHOLD,
    HUMAN_REVIEW,
    MIN_MODEL_CONFIDENCE,
    MONETARY_CEILING,
    decide,
)


@dataclass
class DummyItem:
    field: str
    status: str
    valid: bool = True
    consistent: bool = True
    verified: bool = True


@dataclass
class DummyEvidenceQuality:
    completeness: float
    items: list[DummyItem]


@dataclass
class DummyEvidencePacket:
    pass_count: int
    total: int
    items: list[DummyItem]


def _make_passing_evidence(total: int = 4, pass_count: int = 3):
    items = []
    for i in range(total):
        status = "PASS" if i < pass_count else "WARN"
        items.append(DummyItem(field=f"field_{i}", status=status))
    packet = DummyEvidencePacket(pass_count=pass_count, total=total, items=items)
    quality = DummyEvidenceQuality(completeness=1.0, items=items)
    return packet, quality


class TestPolicyBoundaries:
    """Verifies all threshold boundaries (+- epsilon) and fail-closed guarantees."""

    def test_auto_contest_threshold_epsilon_boundary(self):
        eps = 1e-5
        packet, quality = _make_passing_evidence(total=4, pass_count=3)  # 75% pass > 50%
        amount = 5000.0  # EV > 0

        # Just below threshold -> HUMAN-REVIEW (ambiguous)
        decision_below = decide(
            win_probability=AUTO_CONTEST_THRESHOLD - eps,
            amount=amount,
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=0.8,
        )
        assert decision_below.action == HUMAN_REVIEW
        assert "ambiguous" in decision_below.reason

        # Exactly at threshold -> AUTO-CONTEST
        decision_at = decide(
            win_probability=AUTO_CONTEST_THRESHOLD,
            amount=amount,
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=0.8,
        )
        assert decision_at.action == AUTO_CONTEST

        # Just above threshold -> AUTO-CONTEST
        decision_above = decide(
            win_probability=AUTO_CONTEST_THRESHOLD + eps,
            amount=amount,
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=0.8,
        )
        assert decision_above.action == AUTO_CONTEST

    def test_accept_loss_threshold_epsilon_boundary(self):
        eps = 1e-5
        # Very small amount so EV is negative: win_prob * 100 - 150 < 0
        amount = 100.0

        # Exactly at threshold -> ACCEPT-LOSS
        decision_at = decide(win_probability=ACCEPT_LOSS_THRESHOLD, amount=amount)
        assert decision_at.action == ACCEPT_LOSS

        # Just below threshold -> ACCEPT-LOSS
        decision_below = decide(win_probability=ACCEPT_LOSS_THRESHOLD - eps, amount=amount)
        assert decision_below.action == ACCEPT_LOSS

        # Just above threshold -> HUMAN-REVIEW (ambiguous band)
        decision_above = decide(win_probability=ACCEPT_LOSS_THRESHOLD + eps, amount=amount)
        assert decision_above.action == HUMAN_REVIEW
        assert "ambiguous" in decision_above.reason

    def test_accept_loss_positive_ev_override(self):
        # Even if score <= 0.30, positive EV must route to HUMAN-REVIEW, never accept loss
        amount = 20000.0
        p = 0.25  # EV = 0.25 * 20000 - 150 = +4850 > 0
        decision = decide(win_probability=p, amount=amount)
        assert decision.action == HUMAN_REVIEW
        assert "positive" in decision.reason
        assert decision.expected_value > 0

    def test_monetary_ceiling_boundary(self):
        packet, quality = _make_passing_evidence(total=4, pass_count=3)
        p = 0.80

        # At monetary ceiling -> AUTO-CONTEST
        dec_ceiling = decide(
            win_probability=p,
            amount=MONETARY_CEILING,
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=0.8,
        )
        assert dec_ceiling.action == AUTO_CONTEST

        # 1 rupee over ceiling -> HUMAN-REVIEW
        dec_over = decide(
            win_probability=p,
            amount=MONETARY_CEILING + 1.0,
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=0.8,
        )
        assert dec_over.action == HUMAN_REVIEW
        assert "monetary ceiling" in dec_over.reason

    def test_graph_risk_threshold_boundary(self):
        packet, quality = _make_passing_evidence(total=4, pass_count=3)
        p = 0.80
        amount = 5000.0

        # Just below graph risk escalation threshold -> AUTO-CONTEST
        dec_below = decide(
            win_probability=p,
            amount=amount,
            evidence_packet=packet,
            evidence_quality=quality,
            graph_risk_score=GRAPH_HUMAN_REVIEW_THRESHOLD - 0.01,
            model_confidence=0.8,
        )
        assert dec_below.action == AUTO_CONTEST

        # At graph risk escalation threshold -> HUMAN-REVIEW
        dec_at = decide(
            win_probability=p,
            amount=amount,
            evidence_packet=packet,
            evidence_quality=quality,
            graph_risk_score=GRAPH_HUMAN_REVIEW_THRESHOLD,
            model_confidence=0.8,
        )
        assert dec_at.action == HUMAN_REVIEW
        assert "Relationship risk score" in dec_at.reason

    def test_pass_fraction_strict_inequality_boundary(self):
        # MIN_PASS_FRACTION_FOR_AUTO_CONTEST is 0.50 (must be strictly > 50%)
        # 2 out of 4 is exactly 50% -> BLOCKED
        packet_50, quality_50 = _make_passing_evidence(total=4, pass_count=2)
        dec_50 = decide(
            win_probability=0.80,
            amount=5000.0,
            evidence_packet=packet_50,
            evidence_quality=quality_50,
            model_confidence=0.8,
        )
        assert dec_50.action == HUMAN_REVIEW
        assert "strictly greater" in dec_50.reason

        # 3 out of 4 is 75% > 50% -> ALLOWED
        packet_75, quality_75 = _make_passing_evidence(total=4, pass_count=3)
        dec_75 = decide(
            win_probability=0.80,
            amount=5000.0,
            evidence_packet=packet_75,
            evidence_quality=quality_75,
            model_confidence=0.8,
        )
        assert dec_75.action == AUTO_CONTEST

    def test_model_confidence_boundary(self):
        packet, quality = _make_passing_evidence(total=4, pass_count=3)

        # Just below minimum model confidence -> HUMAN-REVIEW
        dec_low_conf = decide(
            win_probability=0.80,
            amount=5000.0,
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=MIN_MODEL_CONFIDENCE - 0.01,
        )
        assert dec_low_conf.action == HUMAN_REVIEW
        assert "Model confidence" in dec_low_conf.reason

        # At minimum model confidence -> AUTO-CONTEST
        dec_ok_conf = decide(
            win_probability=0.80,
            amount=5000.0,
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=MIN_MODEL_CONFIDENCE,
        )
        assert dec_ok_conf.action == AUTO_CONTEST

    def test_fail_closed_on_invalid_inputs(self):
        # NaN / inf / out-of-bounds win_probability
        for bad_p in [float("nan"), float("inf"), float("-inf"), -0.01, 1.01]:
            dec = decide(win_probability=bad_p, amount=5000.0)
            assert dec.action == HUMAN_REVIEW
            assert "Invalid risk estimate" in dec.reason

        # Zero or negative or non-finite amount
        for bad_amt in [0.0, -100.0, float("nan"), float("inf")]:
            dec = decide(win_probability=0.8, amount=bad_amt)
            assert dec.action == HUMAN_REVIEW
            assert "Invalid dispute amount" in dec.reason

        # NaN / inf / out-of-bounds graph risk score
        for bad_gr in [float("nan"), float("inf"), -0.01, 1.05]:
            dec = decide(win_probability=0.8, amount=5000.0, graph_risk_score=bad_gr)
            assert dec.action == HUMAN_REVIEW
            assert "Invalid relationship risk score" in dec.reason

        # Non-positive EV with high win probability (e.g. tiny amount < contest cost)
        packet, quality = _make_passing_evidence(total=4, pass_count=3)
        dec_tiny = decide(
            win_probability=0.90,
            amount=100.0,  # 0.90 * 100 - 150 = -60 < 0
            evidence_packet=packet,
            evidence_quality=quality,
            model_confidence=0.8,
        )
        assert dec_tiny.action == HUMAN_REVIEW
        assert "expected net value" in dec_tiny.reason

        # Contest count limit reached
        dec_count = decide(
            win_probability=0.80,
            amount=5000.0,
            evidence_packet=packet,
            evidence_quality=quality,
            contest_count=1,
            model_confidence=0.8,
        )
        assert dec_count.action == HUMAN_REVIEW
        assert "Contest count" in dec_count.reason

        # External service unavailable
        dec_unavail = decide(
            win_probability=0.80,
            amount=5000.0,
            evidence_packet=packet,
            evidence_quality=quality,
            external_service_available=False,
            model_confidence=0.8,
        )
        assert dec_unavail.action == HUMAN_REVIEW
        assert "unavailable" in dec_unavail.reason
