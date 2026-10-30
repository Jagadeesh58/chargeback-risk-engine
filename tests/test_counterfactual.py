import os

from chargeback_risk_engine.audit_log import DB_PATH
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case


def teardown_function():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def test_counterfactual_reports_actual_decision_reversal():
    dispute = {
        "dispute_id": "CF_001",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": None,
        "has_signature_confirmation": None,
    }
    result = decide_case(dispute)
    cf = result["counterfactual"]
    assert cf["status"] == "DECISION_CHANGED"
    assert cf["from_action"] == "HUMAN-REVIEW"
    assert cf["to_action"] == "AUTO-CONTEST"
    assert cf["changed_field"] in {"has_delivery_confirmation", "has_signature_confirmation"}
    assert cf["to_value"] is True


def test_counterfactual_does_not_persist_candidate_requests():
    dispute = {
        "dispute_id": "CF_002",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": None,
        "has_signature_confirmation": None,
    }
    result = decide_case(dispute)
    assert result["replayed"] is False
    assert result["counterfactual"]["status"] == "DECISION_CHANGED"
    # Only the production case is persisted; counterfactuals use a temporary audit store.
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    conn.close()
    assert rows == 1


def test_counterfactual_does_not_mutate_risk_graph():
    from chargeback_risk_engine.engine.risk_graph import RiskGraph

    graph = RiskGraph([
        {"dispute_id": "EXISTING_01", "amount": 1000.0, "customer_id": "cust_1", "device_id": "dev_1"},
        {"dispute_id": "EXISTING_02", "amount": 2000.0, "customer_id": "cust_2", "device_id": "dev_2"},
    ])
    dispute = {
        "dispute_id": "CF_003",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "customer_id": "cust_1",
        "has_tracking_number": True,
        "has_delivery_confirmation": None,
        "has_signature_confirmation": None,
    }

    result = decide_case(dispute, risk_graph=graph)
    assert result["counterfactual"] is not None

    # Only dispute:CF_003 is added to the live graph; NO candidate CF_ nodes exist
    candidate_nodes = [
        node for node in graph.node_to_entities
        if "CF_CF_003" in node or (node.startswith("dispute:CF_") and node != "dispute:CF_003")
    ]
    assert len(candidate_nodes) == 0, f"Candidate nodes leaked into shared graph: {candidate_nodes}"
    # Verify entity index only references real nodes
    for entity, nodes in graph.entity_to_nodes.items():
        for node in nodes:
            assert not ("CF_CF_003" in node or (node.startswith("dispute:CF_") and node != "dispute:CF_003"))


def test_counterfactual_only_suggests_actionable_flips():
    """Flipping True -> False is not an actionable suggestion for a merchant."""
    dispute = {
        "dispute_id": "CF_004",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    from chargeback_risk_engine.engine.counterfactual import _candidate_inputs
    candidates = _candidate_inputs(dispute)
    assert len(candidates) == 0, "All fields are True, so no actionable flips should be generated"
