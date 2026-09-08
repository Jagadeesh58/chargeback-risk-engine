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
        "has_delivery_confirmation": True,
        "has_signature_confirmation": None,
    }
    result = decide_case(dispute)
    cf = result["counterfactual"]
    assert cf["status"] == "DECISION_CHANGED"
    assert cf["from_action"] == "AUTO-CONTEST"
    assert cf["to_action"] == "HUMAN-REVIEW"
    assert cf["changed_field"] in {"has_tracking_number", "has_delivery_confirmation"}


def test_counterfactual_does_not_persist_candidate_requests():
    dispute = {
        "dispute_id": "CF_002",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
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
