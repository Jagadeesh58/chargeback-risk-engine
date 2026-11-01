"""Tests for production-grade API features: settings, auth, probes, metrics, security."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chargeback_risk_engine.api import _validate_startup_config, app
from chargeback_risk_engine.audit_log import SQLiteAuditStore
from chargeback_risk_engine.settings import reset_settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_ENV", "development")
    reset_settings()
    yield
    reset_settings()


def test_startup_validation_rejects_debug_in_production(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "a" * 32)
    monkeypatch.setenv("CHARGEBACK_DEBUG", "1")
    with pytest.raises(RuntimeError, match="CHARGEBACK_DEBUG must not be enabled in production"):
        _validate_startup_config()


def test_startup_validation_rejects_wildcard_cors_in_production(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "a" * 32)
    monkeypatch.setenv("CHARGEBACK_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match=r"Wildcard CORS origin '\*' is forbidden"):
        _validate_startup_config()


def test_startup_validation_rejects_db_inside_package(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "a" * 32)
    package_db = Path(__file__).resolve().parents[1] / "chargeback_risk_engine" / "bad.db"
    monkeypatch.setenv("CHARGEBACK_AUDIT_DB_PATH", str(package_db))
    with pytest.raises(RuntimeError, match="cannot be located inside package directory"):
        _validate_startup_config()


def test_multi_key_rotation_and_actor_audit(monkeypatch, tmp_path):
    db_file = tmp_path / "multi_key_audit.db"
    monkeypatch.setenv("CHARGEBACK_DB_PATH", str(db_file))
    monkeypatch.setenv("CHARGEBACK_AUDIT_DB_PATH", str(db_file))
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv(
        "CHARGEBACK_API_KEYS",
        "worker_alpha:alpha-secret-key-at-least-16-chars:decision,worker_beta:beta-secret-key-at-least-16-chars:decision",
    )
    reset_settings()

    client = TestClient(app)

    payload_a = {
        "dispute_id": "D_ACTOR_01",
        "payment_id": "PAY_01",
        "reason_code": "duplicate_charge",
        "amount": 2000.0,
        "has_duplicate_transaction_proof": True,
        "has_duplicate_transaction_proof_source": "psp_log",
        "has_duplicate_transaction_proof_timestamp": "2026-10-31T12:00:00Z",
    }
    resp_a = client.post(
        "/decision",
        json=payload_a,
        headers={"X-API-Key": "alpha-secret-key-at-least-16-chars"},
    )
    assert resp_a.status_code == 200

    payload_b = {
        "dispute_id": "D_ACTOR_02",
        "payment_id": "PAY_02",
        "reason_code": "duplicate_charge",
        "amount": 2500.0,
        "has_duplicate_transaction_proof": True,
        "has_duplicate_transaction_proof_source": "psp_log",
        "has_duplicate_transaction_proof_timestamp": "2026-10-31T12:00:00Z",
    }
    resp_b = client.post(
        "/decision",
        json=payload_b,
        headers={"X-API-Key": "beta-secret-key-at-least-16-chars"},
    )
    assert resp_b.status_code == 200

    store = SQLiteAuditStore(str(db_file))
    rec_a = store.get("D_ACTOR_01")
    assert rec_a is not None
    assert rec_a.actor == "worker_alpha"

    rec_b = store.get("D_ACTOR_02")
    assert rec_b is not None
    assert rec_b.actor == "worker_beta"


def test_readonly_api_key_enforcement(monkeypatch, tmp_path):
    db_file = tmp_path / "readonly_test.db"
    monkeypatch.setenv("CHARGEBACK_DB_PATH", str(db_file))
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv(
        "CHARGEBACK_API_KEYS",
        "scanner:scanner-secret-key-16-chars:readonly",
    )
    reset_settings()

    client = TestClient(app)

    # Read-only key cannot submit decisions
    payload = {
        "dispute_id": "D_RO_01",
        "payment_id": "PAY_RO_01",
        "reason_code": "duplicate_charge",
        "amount": 1000.0,
    }
    resp = client.post(
        "/decision",
        json=payload,
        headers={"X-API-Key": "scanner-secret-key-16-chars"},
    )
    assert resp.status_code == 403
    assert "Read-only API key cannot perform decision operations" in resp.json()["detail"]

    # Read-only key CAN verify audit trail
    verify_resp = client.get(
        "/audit/verify",
        headers={"X-API-Key": "scanner-secret-key-16-chars"},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True


def test_healthz_and_readyz_probes(monkeypatch, tmp_path):
    client = TestClient(app)

    # Liveness probe
    liveness = client.get("/healthz")
    assert liveness.status_code == 200
    assert liveness.json()["status"] == "ok"
    assert "version" in liveness.json()

    # Readiness probe
    readiness = client.get("/readyz")
    assert readiness.status_code == 200
    data = readiness.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "ok"
    assert data["checks"]["model"] == "ok"


def test_prometheus_metrics_endpoint(monkeypatch, tmp_path):
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "chargeback_decisions_total" in resp.text
    assert "chargeback_decision_duration_seconds" in resp.text
    assert "chargeback_audit_writes_total" in resp.text


def test_security_headers_and_request_id(monkeypatch):
    client = TestClient(app)
    resp = client.get("/health", headers={"X-Request-ID": "custom-req-id-12345"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == "custom-req-id-12345"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Strict-Transport-Security" in resp.headers


def test_readyz_database_unreachable(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_DB_PATH", "/nonexistent/path/db.sqlite")
    monkeypatch.setenv("CHARGEBACK_AUDIT_DB_PATH", "/nonexistent/path/db.sqlite")
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "error" in data["checks"]["database"]


def test_readyz_model_hash_mismatch(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_MODEL_SHA256", "0" * 64)
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "error" in data["checks"]["model"]


def test_readyz_audit_chain_tampered(monkeypatch, tmp_path):
    db_file = tmp_path / "tampered_audit.db"
    monkeypatch.setenv("CHARGEBACK_DB_PATH", str(db_file))
    monkeypatch.setenv("CHARGEBACK_AUDIT_DB_PATH", str(db_file))
    store = SQLiteAuditStore(str(db_file))

    from chargeback_risk_engine.audit_log import LoggedDecision

    d1 = LoggedDecision(
        dispute_id="D1",
        reason_code="fraud",
        amount=100.0,
        win_probability=0.5,
        action="AUTO-CONTEST",
        reason="ok",
        expected_value=50.0,
        evidence={},
        created_at="2026-10-31T00:00:00Z",
    )
    store.append(d1)

    # Tamper with row directly in SQLite
    conn = sqlite3.connect(str(db_file))
    conn.execute("UPDATE decisions SET amount = 9999.0 WHERE dispute_id = 'D1'")
    conn.commit()
    conn.close()

    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "error" in data["checks"]["audit_chain"]


def test_metrics_authentication_in_production(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "prod-key-at-least-32-chars-long-abc")
    monkeypatch.setenv("CHARGEBACK_API_KEYS", "client-1:prod-key-at-least-32-chars-long-abc:write")
    monkeypatch.setenv("CHARGEBACK_METRICS_KEY", "metrics-secret-key-12345")
    from chargeback_risk_engine.settings import reset_settings

    reset_settings()

    client = TestClient(app)

    # 1. Unauthenticated in production -> 401
    resp_unauth = client.get("/metrics")
    assert resp_unauth.status_code == 401

    # 2. Authenticated with standard API key -> 200
    resp_apikey = client.get(
        "/metrics", headers={"X-API-Key": "prod-key-at-least-32-chars-long-abc"}
    )
    assert resp_apikey.status_code == 200
    assert "chargeback_decisions_total" in resp_apikey.text

    # 3. Authenticated with CHARGEBACK_METRICS_KEY -> 200
    resp_metrics = client.get("/metrics", headers={"X-API-Key": "metrics-secret-key-12345"})
    assert resp_metrics.status_code == 200
