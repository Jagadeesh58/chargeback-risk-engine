"""
test_local_pipeline.py — real, runnable tests for local_pipeline.py.
Deliberately kept separate from app_deployed.py's UI code so importing
this module for testing never triggers Streamlit's page rendering.
"""

import os

import pytest

from local_pipeline import score_dispute_locally
from audit_log import DB_PATH


@pytest.fixture(autouse=True)
def clean_audit_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def test_strong_evidence_auto_contests():
    dispute = {
        "dispute_id": "D_LOCAL_1",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    result = score_dispute_locally(dispute)
    assert result["action"] == "AUTO-CONTEST"
    assert result["replayed"] is False
    assert result["contest_draft"]["action"] == "draft"


def test_matches_api_pipeline_exactly():
    """Cross-check: local_pipeline.py's output for a given dispute must
    exactly match api.py's /score endpoint's output for the same input --
    proving the deployed app's logic hasn't silently diverged from the
    real API."""
    from fastapi.testclient import TestClient
    from api import app as fastapi_app

    dispute = {
        "dispute_id": "D_CROSS_CHECK",
        "reason_code": "unauthorized_transaction",
        "amount": 1500.0,
        "has_avs_match": True,
        "has_cvv_match": False,
        "has_device_fingerprint_match": None,
    }

    local_result = score_dispute_locally(dict(dispute))

    # Reset the audit db so the API call is also a fresh, first-time decision
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    client = TestClient(fastapi_app)
    api_result = client.post("/score", json={
        "payment_id": "pay_cross_check",
        **dispute,
    }).json()

    assert local_result["action"] == api_result["action"]
    assert local_result["win_probability"] == api_result["win_probability"]
    assert local_result["calibrated_win_probability"] == api_result["calibrated_win_probability"]
    assert local_result["expected_value"] == api_result["expected_value"]
    assert local_result["contest_draft"] == api_result["contest_draft"]


def test_over_ceiling_amount_forces_human_review():
    dispute = {
        "dispute_id": "D_LOCAL_CEILING",
        "reason_code": "item_not_received",
        "amount": 800000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    result = score_dispute_locally(dispute)
    assert result["action"] == "HUMAN REVIEW"
    assert "ceiling" in result["reason"].lower()


def test_idempotency_same_dispute_id_twice():
    dispute = {
        "dispute_id": "D_LOCAL_IDEM",
        "reason_code": "item_not_received",
        "amount": 2000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    first = score_dispute_locally(dict(dispute))
    second = score_dispute_locally(dict(dispute))
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert first["win_probability"] == second["win_probability"]
    assert first["calibrated_win_probability"] == second["calibrated_win_probability"]
    assert first["contest_draft"] == second["contest_draft"]