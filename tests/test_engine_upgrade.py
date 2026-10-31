from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.engine.feedback import record_outcome
from chargeback_risk_engine.engine.risk_graph import RiskGraph
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.policy import MONETARY_CEILING, decide


def test_evidence_score_treats_missing_as_low_confidence():
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": None,
        "has_signature_confirmation": None,
    }
    packet = assemble(dispute)
    scored = score_evidence(dispute, packet)
    assert scored.completeness == 1 / 3
    assert scored.confidence < 0.6


def test_economic_decision_negative_value_is_no_action():
    result = calculate_economic_value(100, 0.5, contest_cost=150)
    assert result.expected_net_value < 0
    assert result.economically_viable is False


def test_policy_positive_economic_value_is_required_for_auto_contest():
    decision = decide(0.99, 100, evidence_packet=None, expected_net_value=-1)
    assert decision.action == "HUMAN-REVIEW"


def test_policy_external_failure_falls_back_to_human():
    decision = decide(0.99, 1000, external_service_available=False)
    assert decision.action == "HUMAN-REVIEW"


def test_policy_contest_count_limit_is_enforced():
    decision = decide(0.99, 1000, contest_count=1)
    assert decision.action == "HUMAN-REVIEW"


def test_ceiling_still_wins_with_new_gates():
    decision = decide(1.0, MONETARY_CEILING + 1, expected_net_value=999999)
    assert decision.action == "HUMAN-REVIEW"


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


def test_risk_graph_merchant_id_does_not_trigger_fraud_escalation():
    """Verify that multiple unrelated disputes sharing only merchant_id are NOT linked."""
    rows = [
        {
            "dispute_id": f"d_{i}",
            "merchant_id": "merchant_busy_1",
            "customer_id": f"cust_{i}",
            "device_id": f"dev_{i}",
            "ip_address": f"192.168.1.{i}",
            "card_fingerprint": f"card_{i}",
            "amount": 1000.0,
        }
        for i in range(15)
    ]
    graph = RiskGraph(rows)
    for row in rows:
        analysis = graph.analyze(row)
        assert analysis.cluster_size == 1
        assert analysis.risk_type == "NO_CLUSTER"
        assert analysis.risk_score == 0.0
        assert len(analysis.suspicious_clusters) == 0


def test_risk_graph_nat_hub_cap_does_not_escalate_to_organized_abuse():
    """50 distinct customers on one shared ISP NAT IP must not escalate to ORGANIZED_ABUSE due to hub cap."""
    rows = [
        {
            "dispute_id": f"d_{i}",
            "customer_id": f"cust_{i}",
            "device_id": f"dev_{i}",
            "ip_address": "198.51.100.1",
            "card_fingerprint": f"card_{i}",
            "amount": 2000.0,
        }
        for i in range(50)
    ]
    graph = RiskGraph(rows, max_hub_degree=20)
    new_dispute = {
        "dispute_id": "d_50",
        "customer_id": "cust_50",
        "device_id": "dev_50",
        "ip_address": "198.51.100.1",
        "card_fingerprint": "card_50",
        "amount": 2000.0,
    }
    analysis = graph.analyze(new_dispute)
    assert analysis.risk_type != "ORGANIZED_ABUSE"
    assert analysis.cluster_size == 1
    assert analysis.risk_score < 0.60


def test_load_graph_rows_subgraph_2_hops(tmp_path):
    from chargeback_risk_engine.audit_log import load_graph_rows, log_new_decision

    db = str(tmp_path / "subgraph_test.db")
    log_new_decision(
        "D1",
        "item_not_received",
        1000.0,
        0.8,
        "AUTO-CONTEST",
        "test",
        800.0,
        [],
        db_path=db,
        graph_data={"customer_id": "c1", "ip_address": "1.1.1.1"},
    )
    log_new_decision(
        "D2",
        "item_not_received",
        1000.0,
        0.8,
        "AUTO-CONTEST",
        "test",
        800.0,
        [],
        db_path=db,
        graph_data={"customer_id": "c2", "ip_address": "1.1.1.1", "device_id": "dev_shared"},
    )
    log_new_decision(
        "D3",
        "item_not_received",
        1000.0,
        0.8,
        "AUTO-CONTEST",
        "test",
        800.0,
        [],
        db_path=db,
        graph_data={"customer_id": "c3", "device_id": "dev_shared"},
    )
    for i in range(20):
        log_new_decision(
            f"UNRELATED_{i}",
            "item_not_received",
            500.0,
            0.5,
            "HUMAN-REVIEW",
            "test",
            0.0,
            [],
            db_path=db,
            graph_data={"customer_id": f"unrel_{i}", "ip_address": f"10.0.0.{i}"},
        )

    subgraph = load_graph_rows(db, dispute={"customer_id": "c1"})
    found_ids = {r["dispute_id"] for r in subgraph}
    assert "D1" in found_ids
    assert "D2" in found_ids
    assert "D3" in found_ids
    assert not any(r["dispute_id"].startswith("UNRELATED_") for r in subgraph)


def test_feedback_is_idempotent_by_dispute_id(tmp_path):
    db = str(tmp_path / "audit.db")
    first = record_outcome(db, "d1", 0.8, "AUTO-CONTEST", recovered_amount=100)
    second = record_outcome(db, "d1", 0.7, "HUMAN-REVIEW", recovered_amount=50)
    assert first.dispute_id == second.dispute_id
    assert second.predicted_probability == 0.7
