"""Regression tests for evidence provenance, timestamp validation, and fail-field gates."""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app
from chargeback_risk_engine.audit_log import DB_PATH
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.policy import ACCEPT_LOSS, AUTO_CONTEST, HUMAN_REVIEW, decide

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


def test_omission_of_provenance_in_production_routes_to_human_review(monkeypatch):
    """In production mode, omitting provenance fields marks positive evidence unverified and routes to HUMAN-REVIEW."""
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "prod_super_secret_api_key_32chars_min_length!!")
    monkeypatch.delenv("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", raising=False)

    payload = {
        "dispute_id": "D_OMIT_PROD_001",
        "payment_id": "pay_omit_1",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    headers = {"X-API-Key": "prod_super_secret_api_key_32chars_min_length!!"}
    response = client.post("/decision", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == HUMAN_REVIEW
    assert "unverified" in data["reason"].lower()


def test_verified_provenance_in_production_routes_to_auto_contest(monkeypatch):
    """In production mode, full verified provenance allows auto-contest."""
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "prod_super_secret_api_key_32chars_min_length!!")
    monkeypatch.delenv("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", raising=False)

    valid_ts = _now_iso(offset_days=-1.0)
    payload = {
        "dispute_id": "D_VERIFY_PROD_001",
        "payment_id": "pay_ver_1",
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
    headers = {"X-API-Key": "prod_super_secret_api_key_32chars_min_length!!"}
    response = client.post("/decision", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == AUTO_CONTEST


def test_dev_override_works_and_is_reported_by_health(monkeypatch):
    """In development mode, CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE=1 relaxes provenance and is reported by /health."""
    monkeypatch.setenv("CHARGEBACK_ENV", "development")
    monkeypatch.setenv("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "1")

    # Verify /health reports it
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["allow_unverified_evidence"] is True
    assert health_data["environment"] == "development"

    # Request without provenance can AUTO-CONTEST in dev when override is active
    payload = {
        "dispute_id": "D_DEV_OVERRIDE_001",
        "payment_id": "pay_dev_1",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    resp = client.post("/decision", json=payload)
    assert resp.status_code == 200
    assert resp.json()["action"] == AUTO_CONTEST


from unittest import mock

import hypothesis.strategies as st
from hypothesis import given, settings


@settings(max_examples=25, deadline=None)
@given(
    source=st.sampled_from(
        [None, "", "manual_upload", "unknown", "arbitrary_user_upload", "untrusted"]
    ),
    timestamp_offset=st.sampled_from([None, 10.0, -500.0]),  # None, future, stale (>365d)
)
def test_hypothesis_no_unverified_provenance_ever_auto_contests_in_production(
    source, timestamp_offset
):
    """Property-based test: in production, no dispute with missing/untrusted/out-of-window provenance ever yields AUTO-CONTEST."""
    env_patch = {
        "CHARGEBACK_ENV": "production",
        "CHARGEBACK_API_KEY": "prod_super_secret_api_key_32chars_min_length!!",
    }
    with mock.patch.dict(os.environ, env_patch):
        os.environ.pop("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", None)
        ts_str = _now_iso(offset_days=timestamp_offset) if timestamp_offset is not None else None
        dispute = {
            "dispute_id": "D_HYPO_TEST",
            "payment_id": "pay_hypo",
            "reason_code": "item_not_received",
            "amount": 2000.0,
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        }
        if source is not None:
            dispute["has_tracking_number_source"] = source
        if ts_str is not None:
            dispute["has_tracking_number_timestamp"] = ts_str

        packet = assemble(dispute)
        quality = score_evidence(dispute, packet)

        # Even with an artificially high win_probability of 0.99 and expected value of 1800,
        # policy.decide must reject AUTO-CONTEST.
        decision = decide(
            win_probability=0.99,
            amount=2000.0,
            evidence_packet=packet,
            evidence_quality=quality,
            expected_net_value=1800.0,
        )
        assert decision.action != AUTO_CONTEST, (
            f"Unverified source={source}, ts={ts_str} unexpectedly reached AUTO-CONTEST"
        )
