"""Tests that verify the example JSON payloads and example client work against the API."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app
from chargeback_risk_engine.settings import reset_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"


def test_example_payloads_exist():
    assert (EXAMPLES_DIR / "request_verified.json").exists()
    assert (EXAMPLES_DIR / "request_unverified.json").exists()
    assert (EXAMPLES_DIR / "python_client.py").exists()
    assert (EXAMPLES_DIR / "quickstart.sh").exists()


def test_verified_example_routes_to_auto_contest(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "prod-test-key-at-least-32-chars-long")
    monkeypatch.setenv("CHARGEBACK_API_KEYS", "client-1:prod-test-key-at-least-32-chars-long:write")
    reset_settings()

    client = TestClient(app)
    payload = json.loads((EXAMPLES_DIR / "request_verified.json").read_text(encoding="utf-8"))
    payload["dispute_id"] = "TEST_EX_VERIFIED_001"

    resp = client.post(
        "/decision",
        json=payload,
        headers={"X-API-Key": "prod-test-key-at-least-32-chars-long"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "AUTO-CONTEST"
    assert data["amount"] == 3500.0


def test_unverified_example_fails_closed_in_production(monkeypatch):
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.setenv("CHARGEBACK_API_KEY", "prod-test-key-at-least-32-chars-long")
    monkeypatch.setenv("CHARGEBACK_API_KEYS", "client-1:prod-test-key-at-least-32-chars-long:write")
    reset_settings()

    client = TestClient(app)
    payload = json.loads((EXAMPLES_DIR / "request_unverified.json").read_text(encoding="utf-8"))
    payload["dispute_id"] = "TEST_EX_UNVERIFIED_001"

    resp = client.post(
        "/decision",
        json=payload,
        headers={"X-API-Key": "prod-test-key-at-least-32-chars-long"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # In production mode, unverified evidence fails closed to HUMAN-REVIEW
    assert data["action"] == "HUMAN-REVIEW"
    assert "provenance" in data["reason"].lower() or "unverified" in data["reason"].lower()
