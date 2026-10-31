"""
test_api.py — real, runnable tests for api.py. Uses FastAPI's TestClient,
which calls the app directly in-process (no real network needed), but
still exercises the full request -> validation -> pipeline -> response
path exactly as a real HTTP call would.
"""

import os

import pytest
from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app
from chargeback_risk_engine.audit_log import DB_PATH

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
    data = response.json()
    assert data["status"] == "ok"
    assert data["auth"] in ("demo-open", "api-key")


def test_score_strong_evidence_auto_contests():
    response = client.post(
        "/decision",
        json={
            "dispute_id": "D0001",
            "payment_id": "pay_ABC",
            "reason_code": "item_not_received",
            "amount": 2000,
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        },
    )
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
    response = client.post(
        "/score",
        json={
            "dispute_id": "D0007",
            "payment_id": "pay_PQR",
            "reason_code": "item_not_received",
            "amount": 1000,
            "has_tracking_number": True,
            "has_delivery_confirmation": None,
            "has_signature_confirmation": False,
        },
    )
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
    route to HUMAN-REVIEW even through the real HTTP layer, proving
    api.py did not accidentally re-implement (and potentially break)
    the ceiling logic."""
    response = client.post(
        "/score",
        json={
            "dispute_id": "D0002",
            "payment_id": "pay_XYZ",
            "reason_code": "item_not_received",
            "amount": 800000,
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "HUMAN-REVIEW"
    assert "ceiling" in data["reason"].lower()


def test_score_unknown_evidence_maps_to_warn_via_api():
    response = client.post(
        "/score",
        json={
            "dispute_id": "D0003",
            "payment_id": "pay_DEF",
            "reason_code": "item_not_received",
            "amount": 1000,
            "has_tracking_number": True,
            # has_delivery_confirmation and has_signature_confirmation omitted entirely
        },
    )
    assert response.status_code == 200
    data = response.json()
    statuses = {item["field"]: item["status"] for item in data["evidence"]}
    assert statuses["has_tracking_number"] == "PASS"
    assert statuses["has_delivery_confirmation"] == "WARN"
    assert statuses["has_signature_confirmation"] == "WARN"


def test_score_missing_required_field_returns_422():
    """Pydantic validation should reject a request missing a required
    field (e.g. no reason_code) BEFORE it ever reaches the pipeline."""
    response = client.post(
        "/score",
        json={
            "dispute_id": "D0004",
            "payment_id": "pay_GHI",
            "amount": 1000,
            # reason_code missing entirely
        },
    )
    assert response.status_code == 422


def test_score_invalid_reason_code_returns_422():
    """An unrecognized reason_code must be rejected with a clean 422
    at the API boundary, not allowed to fall through to scorer.py's
    dict lookup and raise an unhandled KeyError (a 500)."""
    response = client.post(
        "/score",
        json={
            "dispute_id": "D0006",
            "payment_id": "pay_MNO",
            "reason_code": "not_a_real_reason_code",
            "amount": 1000,
        },
    )
    assert response.status_code == 422


def test_response_shape_matches_evidence_module_directly():
    """Cross-check: the API's evidence output for a given dispute should
    exactly match calling evidence.assemble() directly -- proving api.py
    isn't silently duplicating or diverging from the tested logic."""
    from chargeback_risk_engine.evidence import assemble

    dispute = {
        "reason_code": "duplicate_charge",
        "has_duplicate_transaction_proof": True,
        "has_refund_already_issued": False,
    }
    direct_packet = assemble(dispute)

    response = client.post(
        "/score",
        json={
            "dispute_id": "D0005",
            "payment_id": "pay_JKL",
            "reason_code": "duplicate_charge",
            "amount": 1000,
            "has_duplicate_transaction_proof": True,
            "has_refund_already_issued": False,
        },
    )
    api_statuses = {item["field"]: item["status"] for item in response.json()["evidence"]}
    direct_statuses = {item.field: item.status for item in direct_packet.items}
    assert api_statuses == direct_statuses


def test_calibrated_win_probability_matches_calibration_module_directly():
    """Cross-check: the API's calibrated_win_probability should exactly
    match calling calibration.apply_calibration() directly on the same
    win_probability -- proving api.py isn't reimplementing calibration
    itself."""
    from chargeback_risk_engine.calibration import apply_calibration, load_or_fit_calibration_points

    response = client.post(
        "/score",
        json={
            "dispute_id": "D0008",
            "payment_id": "pay_STU",
            "reason_code": "item_not_received",
            "amount": 2000,
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        },
    )
    data = response.json()
    points = load_or_fit_calibration_points()
    expected = apply_calibration(points, data["win_probability"])
    assert data["calibrated_win_probability"] == expected


def test_live_win_probability_matches_ml_scorer_module_directly():
    from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer

    response = client.post(
        "/decision",
        json={
            "dispute_id": "D0009",
            "payment_id": "pay_VWX",
            "reason_code": "item_not_received",
            "amount": 2000,
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        },
    )
    data = response.json()
    scorer = load_or_fit_ml_scorer()
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    expected = scorer.predict_win_probability(dispute)
    assert data["win_probability"] == expected


def test_mutated_replay_uses_only_original_request_context():
    """A retry with changed evidence/amount must return HTTP 409 Conflict,
    naming the conflicting dispute_id, without overwriting the original decision."""
    payload = {
        "dispute_id": "D_API_MUTATED_REPLAY",
        "payment_id": "pay_original",
        "reason_code": "item_not_received",
        "amount": 3000,
        "device_id": "device-original",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    first = client.post("/score", json=payload)
    assert first.status_code == 200
    first_data = first.json()

    # Identical payload replays with 200 and replayed=True
    exact = client.post("/score", json=payload)
    assert exact.status_code == 200
    assert exact.json()["replayed"] is True

    # Mutated payload returns 409 Conflict naming the dispute_id
    mutated = dict(payload)
    mutated.update(
        {
            "amount": 9999,
            "device_id": "device-mutated",
            "has_tracking_number": False,
            "has_delivery_confirmation": False,
            "has_signature_confirmation": False,
        }
    )
    second = client.post("/score", json=mutated)
    assert second.status_code == 409
    assert "D_API_MUTATED_REPLAY" in second.json()["detail"]

    # Verify original row was never overwritten
    third = client.post("/score", json=payload)
    assert third.status_code == 200
    assert third.json()["amount"] == 3000
    assert third.json()["replayed"] is True


def test_live_api_graph_uses_persisted_relationship_history():
    """The API must see identifiers from prior disputes instead of creating
    a fresh empty graph for every request."""
    common = {
        "payment_id": "pay_graph",
        "reason_code": "item_not_received",
        "amount": 1000,
        "device_id": "device-shared-live",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    for index in range(5):
        response = client.post("/score", json={"dispute_id": f"D_GRAPH_{index}", **common})
        assert response.status_code == 200

    final = client.post("/score", json={"dispute_id": "D_GRAPH_FINAL", **common})
    assert final.status_code == 200
    data = final.json()

    assert data["graph_analysis"]["cluster_size"] >= 6
    assert data["graph_analysis"]["connected_accounts"] == 0
    assert "device_id" in data["graph_analysis"]["shared_identifiers"]
    assert data["graph_analysis"]["historical_disputed_value"] >= 6000.0


def test_apps_api_audit_verify_endpoint_uses_canonical_audit_checker():
    """The deployable apps.api wrapper must expose the audit verifier without
    duplicating or breaking the canonical audit implementation."""
    from apps.api import app as deployed_app

    deployed_client = TestClient(deployed_app)
    response = deployed_client.get("/audit/verify")

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert "checked" in data


# ---------------------------------------------------------------------------
# API Hardening Tests (Auth, Rate Limit, Size Limit, Model Hash Integrity)
# ---------------------------------------------------------------------------


def test_api_key_auth_flow(monkeypatch):
    """Test demo mode, missing key, wrong key, and correct key."""
    from chargeback_risk_engine.api import _reset_rate_limiter

    _reset_rate_limiter()

    sample_payload = {
        "dispute_id": "D_AUTH_TEST_1",
        "payment_id": "pay_auth",
        "reason_code": "item_not_received",
        "amount": 1000.0,
        "has_tracking_number": True,
    }

    # 1. Unset -> Demo mode
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)
    health = client.get("/health").json()
    assert health["auth"] == "demo-open"
    resp = client.post("/decision", json=sample_payload)
    assert resp.status_code == 200

    # 2. Key set -> Missing key returns 401
    monkeypatch.setenv("CHARGEBACK_API_KEY", "secret-test-key-123")
    health = client.get("/health").json()
    assert health["auth"] == "api-key"

    # Health remains open without credentials
    health_resp = client.get("/health")
    assert health_resp.status_code == 200

    # Decision without key is rejected
    unauth = client.post("/decision", json=sample_payload)
    assert unauth.status_code == 401

    # Decision with wrong key is rejected
    wrong = client.post("/decision", json=sample_payload, headers={"X-API-Key": "wrong-key"})
    assert wrong.status_code == 401

    # Decision with correct key succeeds
    sample_payload["dispute_id"] = "D_AUTH_TEST_2"
    correct = client.post(
        "/decision", json=sample_payload, headers={"X-API-Key": "secret-test-key-123"}
    )
    assert correct.status_code == 200


def test_request_body_size_limit(monkeypatch):
    """Payloads exceeding maximum body size should return 413."""
    from chargeback_risk_engine.api import _reset_rate_limiter

    _reset_rate_limiter()
    monkeypatch.setenv("CHARGEBACK_MAX_BODY_BYTES", "512")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)

    large_payload = {
        "dispute_id": "D_LARGE",
        "payment_id": "pay_large",
        "reason_code": "item_not_received",
        "amount": 1000.0,
        "customer_id": "x" * 1000,
    }
    resp = client.post("/decision", json=large_payload)
    assert resp.status_code == 413


def test_rate_limiter_enforcement(monkeypatch):
    """Requests exceeding rate limit return 429 with Retry-After header."""
    from chargeback_risk_engine.api import _reset_rate_limiter

    _reset_rate_limiter()
    monkeypatch.setenv("CHARGEBACK_RATE_LIMIT", "2")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)

    payload = {
        "dispute_id": "D_RATE_1",
        "payment_id": "pay_rate",
        "reason_code": "item_not_received",
        "amount": 1000.0,
    }
    headers = {"X-Client-Id": "test-rate-client"}

    r1 = client.post("/decision", json=payload, headers=headers)
    assert r1.status_code == 200

    payload["dispute_id"] = "D_RATE_2"
    r2 = client.post("/decision", json=payload, headers=headers)
    assert r2.status_code == 200

    payload["dispute_id"] = "D_RATE_3"
    r3 = client.post("/decision", json=payload, headers=headers)
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers


def test_model_hash_verification(tmp_path, monkeypatch):
    """Loading model with corrupted/mismatched sidecar hash raises ValueError."""
    import chargeback_risk_engine.ml_scorer as ml_mod

    monkeypatch.setattr(ml_mod, "_cached_scorer", None)

    fake_model = tmp_path / "test_model.json"
    fake_model.write_bytes(b"dummy model bytes")

    sidecar = tmp_path / "test_model.json.sha256"
    sidecar.write_text("invalid_hash_value\n")

    with pytest.raises(ValueError, match="Model integrity failure"):
        ml_mod.load_or_fit_ml_scorer(path=str(fake_model))

    # Correct hash allows load to proceed (will fail on format, but integrity passes)
    import hashlib

    correct_hash = hashlib.sha256(b"dummy model bytes").hexdigest()
    sidecar.write_text(correct_hash + "\n")
    with pytest.raises(RuntimeError, match="invalid model artifact format"):
        ml_mod.load_or_fit_ml_scorer(path=str(fake_model))

    # Requiring hash sidecar when missing
    missing_sidecar_model = tmp_path / "no_sidecar.json"
    missing_sidecar_model.write_bytes(b"{}")
    monkeypatch.setenv("CHARGEBACK_REQUIRE_MODEL_HASH", "1")
    with pytest.raises(ValueError, match="missing required sidecar hash"):
        ml_mod.load_or_fit_ml_scorer(path=str(missing_sidecar_model))


def test_streaming_chunked_body_size_limit_aborts(monkeypatch):
    """Chunked transfer payloads exceeding max_bytes abort with 413."""
    from chargeback_risk_engine.api import _reset_rate_limiter

    _reset_rate_limiter()
    monkeypatch.setenv("CHARGEBACK_MAX_BODY_BYTES", "512")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)

    def chunk_generator():
        for _ in range(10):
            yield b"x" * 200

    resp = client.post(
        "/decision", content=chunk_generator(), headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413


def test_rate_limiter_evaluates_before_body_parsing(monkeypatch):
    """Rate limited client receives 429 even when sending an oversized body."""
    from chargeback_risk_engine.api import _reset_rate_limiter

    _reset_rate_limiter()
    monkeypatch.setenv("CHARGEBACK_RATE_LIMIT", "1")
    monkeypatch.setenv("CHARGEBACK_MAX_BODY_BYTES", "512")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)
    headers = {"X-Client-Id": "pre-rate-client"}

    r1 = client.post(
        "/decision",
        json={
            "dispute_id": "D_PRE_1",
            "payment_id": "p1",
            "reason_code": "item_not_received",
            "amount": 1000.0,
        },
        headers=headers,
    )
    assert r1.status_code == 200

    oversized = {
        "dispute_id": "D_PRE_2",
        "payment_id": "p2",
        "reason_code": "item_not_received",
        "amount": 1000.0,
        "x": "x" * 2000,
    }
    r2 = client.post("/decision", json=oversized, headers=headers)
    assert r2.status_code == 429


def test_startup_warning_when_api_key_unset(monkeypatch, caplog):
    import logging

    from chargeback_risk_engine.api import _validate_startup_config

    monkeypatch.setenv("CHARGEBACK_ENV", "development")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING):
        _validate_startup_config()
    assert "CHARGEBACK_API_KEY is not set" in caplog.text


def test_production_startup_validation(monkeypatch):
    """In production mode, API must refuse to start without a valid key (>=32 chars)."""
    from chargeback_risk_engine.api import _validate_startup_config

    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CHARGEBACK_API_KEY must be set in production mode"):
        _validate_startup_config()

    # Too short key (<32 chars)
    monkeypatch.setenv("CHARGEBACK_API_KEY", "short-key-123")
    with pytest.raises(RuntimeError, match="at least 32 characters in production mode"):
        _validate_startup_config()

    # Valid key (>=32 chars) passes
    monkeypatch.setenv("CHARGEBACK_API_KEY", "a" * 32)
    _validate_startup_config()  # Should not raise


def test_production_auth_protection(monkeypatch):
    """Production mode protects /decision, /score, and /audit/verify with 401."""
    prod_key = "a" * 32
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", prod_key)

    sample = {
        "dispute_id": "D_PROD_AUTH",
        "payment_id": "pay_prod",
        "reason_code": "item_not_received",
        "amount": 1500.0,
        "has_tracking_number": True,
    }

    # /health is open and reports production
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["environment"] == "production"
    assert h.json()["auth"] == "api-key"

    # Missing key -> 401
    assert client.post("/decision", json=sample).status_code == 401
    assert client.post("/score", json=sample).status_code == 401
    assert client.get("/audit/verify").status_code == 401

    # Wrong key -> 401
    assert (
        client.post("/decision", json=sample, headers={"X-API-Key": "wrong" * 8}).status_code == 401
    )
    assert client.get("/audit/verify", headers={"X-API-Key": "wrong" * 8}).status_code == 401

    # Correct key -> 200
    r_dec = client.post("/decision", json=sample, headers={"X-API-Key": prod_key})
    assert r_dec.status_code == 200

    r_audit = client.get("/audit/verify", headers={"X-API-Key": prod_key})
    assert r_audit.status_code == 200


def test_payload_conflict_returns_409_stable_body(monkeypatch):
    """FastAPI TestClient: same dispute_id + different payload -> 409 with stable schema; same -> 200 replayed."""
    monkeypatch.setenv("CHARGEBACK_ENV", "development")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)

    payload_1 = {
        "dispute_id": "D_CONFLICT_TEST",
        "payment_id": "pay_conf_1",
        "reason_code": "item_not_received",
        "amount": 2500.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }

    r1 = client.post("/decision", json=payload_1)
    assert r1.status_code == 200
    assert r1.json()["replayed"] is False

    # Exact replay -> 200 with replayed: True
    r2 = client.post("/decision", json=payload_1)
    assert r2.status_code == 200
    assert r2.json()["replayed"] is True

    # Conflicting payload -> 409 with stable JSON body
    payload_conflicting = dict(payload_1)
    payload_conflicting["amount"] = 8888.0
    payload_conflicting["has_tracking_number"] = False

    r3 = client.post("/decision", json=payload_conflicting)
    assert r3.status_code == 409
    body = r3.json()
    assert body["error"] == "payload_conflict"
    assert body["dispute_id"] == "D_CONFLICT_TEST"
