"""Regression tests for evidence provenance, timestamp validation, and fail-field gates."""
from datetime import datetime, timezone, timedelta
import os
import pytest
from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app
from chargeback_risk_engine.audit_log import DB_PATH
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.policy import decide, AUTO_CONTEST, HUMAN_REVIEW, ACCEPT_LOSS

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_audit_db():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except OSError:
            pass
    yield
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except OSError:
            pass


def _now_iso(offset_days: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=offset_days)
    return dt.isoformat()


def test_extra_field_rejected_with_422():
    payload = {
        "dispute_id": "D_EXTRA_001",
        "payment_id": "pay_extra",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "unexpected_field": "malicious_injection",
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 422


def test_future_timestamp_rejected_with_422():
    future_ts = _now_iso(offset_days=5.0)
    payload = {
        "dispute_id": "D_FUTURE_001",
        "payment_id": "pay_future",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "evidence_timestamp": future_ts,
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 422


def test_stale_timestamp_rejected_with_422():
    stale_ts = _now_iso(offset_days=-400.0)
    payload = {
        "dispute_id": "D_STALE_001",
        "payment_id": "pay_stale",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number_timestamp": stale_ts,
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 422


def test_malformed_timestamp_rejected_with_422():
    payload = {
        "dispute_id": "D_MALFORMED_001",
        "payment_id": "pay_malformed",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "evidence_timestamp": "invalid-non-iso-timestamp",
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 422


def test_unverified_manual_upload_source_cannot_auto_contest():
    valid_ts = _now_iso(offset_days=-1.0)
    payload = {
        "dispute_id": "D_UNVERIFIED_001",
        "payment_id": "pay_unverified_1",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_tracking_number_source": "manual_upload",
        "has_tracking_number_timestamp": valid_ts,
        "has_delivery_confirmation": True,
        "has_delivery_confirmation_source": "carrier_api",
        "has_delivery_confirmation_timestamp": valid_ts,
        "has_signature_confirmation": True,
        "has_signature_confirmation_source": "carrier_api",
        "has_signature_confirmation_timestamp": valid_ts,
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "HUMAN-REVIEW"
    assert "unverified" in data["reason"].lower()


def test_unverified_unknown_source_cannot_auto_contest():
    valid_ts = _now_iso(offset_days=-1.0)
    payload = {
        "dispute_id": "D_UNVERIFIED_002",
        "payment_id": "pay_unverified_2",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_tracking_number_source": "unknown",
        "has_tracking_number_timestamp": valid_ts,
        "has_delivery_confirmation": True,
        "has_delivery_confirmation_source": "carrier_api",
        "has_delivery_confirmation_timestamp": valid_ts,
        "has_signature_confirmation": True,
        "has_signature_confirmation_source": "carrier_api",
        "has_signature_confirmation_timestamp": valid_ts,
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "HUMAN-REVIEW"
    assert "unverified" in data["reason"].lower()


def test_missing_timestamp_with_provenance_tracked_cannot_auto_contest():
    valid_ts = _now_iso(offset_days=-1.0)
    payload = {
        "dispute_id": "D_UNVERIFIED_003",
        "payment_id": "pay_unverified_3",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_tracking_number_source": "carrier_api",
        # Missing has_tracking_number_timestamp
        "has_delivery_confirmation": True,
        "has_delivery_confirmation_source": "carrier_api",
        "has_delivery_confirmation_timestamp": valid_ts,
        "has_signature_confirmation": True,
        "has_signature_confirmation_source": "carrier_api",
        "has_signature_confirmation_timestamp": valid_ts,
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "HUMAN-REVIEW"
    assert "unverified" in data["reason"].lower()


def test_fail_field_hard_stop_blocks_auto_contest():
    """Even with p=0.95 and high expected value, any relevant FAIL field routes to HUMAN-REVIEW."""
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": False,  # FAIL
    }
    packet = assemble(dispute)
    assert packet.fail_count == 1
    quality = score_evidence(dispute, packet)

    # Calling policy.decide with win_probability=0.95
    decision = decide(
        win_probability=0.95,
        amount=2000.0,
        evidence_packet=packet,
        evidence_quality=quality,
        expected_net_value=1750.0,
    )
    assert decision.action == HUMAN_REVIEW
    assert "has_signature_confirmation" in decision.reason
    assert "FAIL" in decision.reason

    # Low probability and non-positive EV routes to ACCEPT-LOSS (hard stop only blocks AUTO-CONTEST)
    loss_decision = decide(
        win_probability=0.10,
        amount=1000.0,
        evidence_packet=packet,
        evidence_quality=quality,
    )
    assert loss_decision.action == ACCEPT_LOSS


def test_verified_all_pass_still_auto_contests():
    valid_ts = _now_iso(offset_days=-1.0)
    payload = {
        "dispute_id": "D_VERIFIED_001",
        "payment_id": "pay_verified_1",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_tracking_number_source": "carrier_api",
        "has_tracking_number_timestamp": valid_ts,
        "has_delivery_confirmation": True,
        "has_delivery_confirmation_source": "carrier_api",
        "has_delivery_confirmation_timestamp": valid_ts,
        "has_signature_confirmation": True,
        "has_signature_confirmation_source": "carrier_api",
        "has_signature_confirmation_timestamp": valid_ts,
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == AUTO_CONTEST


def test_structured_evidence_meta_support():
    valid_ts = _now_iso(offset_days=-2.0)
    payload = {
        "dispute_id": "D_META_001",
        "payment_id": "pay_meta_1",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
        "evidence_meta": {
            "has_tracking_number": {"source": "carrier_api", "timestamp": valid_ts},
            "has_delivery_confirmation": {"source": "carrier_api", "timestamp": valid_ts},
            "has_signature_confirmation": {"source": "carrier_api", "timestamp": valid_ts},
        },
    }
    response = client.post("/decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == AUTO_CONTEST

    # Extra field in evidence_meta rejected with 422
    payload_extra = {
        "dispute_id": "D_META_002",
        "payment_id": "pay_meta_2",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "evidence_meta": {
            "has_tracking_number": {"source": "carrier_api", "unexpected": "value"},
        },
    }
    resp_extra = client.post("/decision", json=payload_extra)
    assert resp_extra.status_code == 422
