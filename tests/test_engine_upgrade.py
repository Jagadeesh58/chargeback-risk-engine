import os

from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.policy import decide, MONETARY_CEILING
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.engine.risk_graph import RiskGraph
from chargeback_risk_engine.engine.feedback import record_outcome


def test_evidence_score_treats_missing_as_low_confidence():
    dispute = {"reason_code": "item_not_received", "has_tracking_number": True, "has_delivery_confirmation": None, "has_signature_confirmation": None}
    packet = assemble(dispute)
    scored = score_evidence(dispute, packet)
    assert scored.completeness == 1 / 3
    assert scored.confidence < 0.6


def test_economic_decision_negative_value_is_no_action():
    result = calculate_economic_value(100, 0.5, contest_cost=150)
    assert result.expected_net_value < 0
    assert result.recommended_action == "NO_ACTION"


def test_policy_positive_economic_value_is_required_for_auto_contest():
    decision = decide(0.99, 100, evidence_packet=None, expected_net_value=-1)
    assert decision.action == "HUMAN REVIEW"


def test_policy_external_failure_falls_back_to_human():
    decision = decide(0.99, 1000, external_service_available=False)
    assert decision.action == "HUMAN REVIEW"


def test_policy_contest_count_limit_is_enforced():
    decision = decide(0.99, 1000, contest_count=1)
    assert decision.action == "HUMAN REVIEW"


def test_ceiling_still_wins_with_new_gates():
    decision = decide(1.0, MONETARY_CEILING + 1, expected_net_value=999999)
    assert decision.action == "HUMAN REVIEW"


def test_risk_graph_detects_shared_device_and_ip():
    rows = [
        {"dispute_id": "d1", "customer_id": "c1", "device_id": "dev-x", "ip_address": "ip-x"},
        {"dispute_id": "d2", "customer_id": "c2", "device_id": "dev-x", "ip_address": "ip-x"},
    ]
    graph = RiskGraph(rows)
    result = graph.analyze(rows[0])
    assert result.cluster_size == 2
    assert "device_id" in result.shared_identifiers
    assert "ip_address" in result.shared_identifiers
    assert result.risk_score > 0


def test_feedback_is_idempotent_by_dispute_id(tmp_path):
    db = str(tmp_path / "audit.db")
    first = record_outcome(db, "d1", 0.8, "AUTO-CONTEST", recovered_amount=100)
    second = record_outcome(db, "d1", 0.7, "HUMAN REVIEW", recovered_amount=50)
    assert first.dispute_id == second.dispute_id
    assert second.predicted_probability == 0.7
