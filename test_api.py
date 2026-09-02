"""
test_api.py — real, runnable tests for api.py. Uses FastAPI's TestClient,
which calls the app directly in-process (no real network needed), but
still exercises the full request -> validation -> pipeline -> response
path exactly as a real HTTP call would.
"""

import os

import pytest
from fastapi.testclient import TestClient

from api import app
from audit_log import DB_PATH

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_audit_db():
    """Ensures each test run starts with a fresh audit log, so repeated
    test runs don't accidentally see old dispute_ids as replays."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_score_strong_evidence_auto_contests():
    response = client.post("/score", json={
        "dispute_id": "D0001",
        "payment_id": "pay_ABC",
        "reason_code": "item_not_received",
        "amount": 2000,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "AUTO-CONTEST"
    assert 0.0 <= data["win_probability"] <= 1.0
    assert 0.0 <= data["calibrated_win_probability"] <= 1.0
    assert len(data["evidence"]) == 3
    assert all(item["status"] == "PASS" for item in data["evidence"])
    assert data["replayed"] is False
    assert data["contest_draft"] is not None
    assert data["contest_draft"]["action"] == "draft"
    assert len(data["contest_draft"]["shipping_proof"]) == 3


def test_score_human_review_has_no_contest_draft():
    """A contest draft only makes sense for AUTO-CONTEST -- there's
    nothing to draft for a dispute that was routed to a human or
    accepted as a loss."""
    response = client.post("/score", json={
        "dispute_id": "D0007",
        "payment_id": "pay_PQR",
        "reason_code": "item_not_received",
        "amount": 1000,
        "has_tracking_number": True,
        "has_delivery_confirmation": None,
        "has_signature_confirmation": False,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["action"] != "AUTO-CONTEST"
    assert data["contest_draft"] is None


def test_duplicate_submission_is_replayed_via_api():
    """Submitting the exact same dispute_id twice through the real API
    should return an identical decision, with replayed=True on the
    second call."""
    payload = {
        "dispute_id": "D_API_IDEMPOTENCY_TEST",
        "payment_id": "pay_dup",
        "reason_code": "item_not_received",
        "amount": 3000,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    first = client.post("/score", json=payload).json()
    second = client.post("/score", json=payload).json()

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert first["action"] == second["action"]
    assert first["win_probability"] == second["win_probability"]
    assert first["calibrated_win_probability"] == second["calibrated_win_probability"]
    assert first["expected_value"] == second["expected_value"]
    assert first["contest_draft"] == second["contest_draft"]


def test_score_over_ceiling_amount_forces_human_review_via_api():
    """The exact end-to-end safety check: an over-ceiling dispute must
    route to HUMAN REVIEW even through the real HTTP layer, proving
    api.py did not accidentally re-implement (and potentially break)
    the ceiling logic."""
    response = client.post("/score", json={
        "dispute_id": "D0002",
        "payment_id": "pay_XYZ",
        "reason_code": "item_not_received",
        "amount": 800000,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "HUMAN REVIEW"
    assert "ceiling" in data["reason"].lower()


def test_score_unknown_evidence_maps_to_warn_via_api():
    response = client.post("/score", json={
        "dispute_id": "D0003",
        "payment_id": "pay_DEF",
        "reason_code": "item_not_received",
        "amount": 1000,
        "has_tracking_number": True,
        # has_delivery_confirmation and has_signature_confirmation omitted entirely
    })
    assert response.status_code == 200
    data = response.json()
    statuses = {item["field"]: item["status"] for item in data["evidence"]}
    assert statuses["has_tracking_number"] == "PASS"
    assert statuses["has_delivery_confirmation"] == "WARN"
    assert statuses["has_signature_confirmation"] == "WARN"


def test_score_missing_required_field_returns_422():
    """Pydantic validation should reject a request missing a required
    field (e.g. no reason_code) BEFORE it ever reaches the pipeline."""
    response = client.post("/score", json={
        "dispute_id": "D0004",
        "payment_id": "pay_GHI",
        "amount": 1000,
        # reason_code missing entirely
    })
    assert response.status_code == 422


def test_score_invalid_reason_code_returns_422():
    """An unrecognized reason_code must be rejected with a clean 422
    at the API boundary, not allowed to fall through to scorer.py's
    dict lookup and raise an unhandled KeyError (a 500)."""
    response = client.post("/score", json={
        "dispute_id": "D0006",
        "payment_id": "pay_MNO",
        "reason_code": "not_a_real_reason_code",
        "amount": 1000,
    })
    assert response.status_code == 422


def test_response_shape_matches_evidence_module_directly():
    """Cross-check: the API's evidence output for a given dispute should
    exactly match calling evidence.assemble() directly -- proving api.py
    isn't silently duplicating or diverging from the tested logic."""
    from evidence import assemble

    dispute = {
        "reason_code": "duplicate_charge",
        "has_duplicate_transaction_proof": True,
        "has_refund_already_issued": False,
    }
    direct_packet = assemble(dispute)

    response = client.post("/score", json={
        "dispute_id": "D0005",
        "payment_id": "pay_JKL",
        "reason_code": "duplicate_charge",
        "amount": 1000,
        "has_duplicate_transaction_proof": True,
        "has_refund_already_issued": False,
    })
    api_statuses = {item["field"]: item["status"] for item in response.json()["evidence"]}
    direct_statuses = {item.field: item.status for item in direct_packet.items}
    assert api_statuses == direct_statuses


def test_calibrated_win_probability_matches_calibration_module_directly():
    """Cross-check: the API's calibrated_win_probability should exactly
    match calling calibration.apply_calibration() directly on the same
    win_probability -- proving api.py isn't reimplementing calibration
    itself."""
    from calibration import apply_calibration, load_or_fit_calibration_points

    response = client.post("/score", json={
        "dispute_id": "D0008",
        "payment_id": "pay_STU",
        "reason_code": "item_not_received",
        "amount": 2000,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    })
    data = response.json()
    points = load_or_fit_calibration_points()
    expected = apply_calibration(points, data["win_probability"])
    assert data["calibrated_win_probability"] == expected