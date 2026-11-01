"""Regression tests converted from scripts/run_hardening_probes.py."""

import concurrent.futures
import json

import pytest
from fastapi.testclient import TestClient

from chargeback_risk_engine.api import _validate_startup_config, app
from chargeback_risk_engine.audit_log import verify_audit_integrity
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.risk_graph import GRAPH_ESCALATION_THRESHOLD, RiskGraph
from chargeback_risk_engine.ml_scorer import (
    load_or_fit_ml_scorer,
    reset_cached_ml_scorer,
    save_ml_scorer,
)
from chargeback_risk_engine.settings import reset_settings


def test_probe_concurrent_decisions_and_audit_hash_integrity(tmp_path):
    """Probe 1: Concurrent decisions produce unbroken cryptographic audit hash chain."""
    db_path = str(tmp_path / "probe1_audit.db")

    def make_decision(i: int):
        dispute = {
            "dispute_id": f"CONCUR_{i:03d}",
            "reason_code": "item_not_received",
            "amount": 1000.0 + i,
            "customer_id": f"cust_{i}",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        }
        return decide_case(dispute, db_path=db_path, include_counterfactual=False)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(make_decision, range(24)))

    integrity = verify_audit_integrity(db_path)
    assert len(results) == 24
    assert integrity["valid"] is True
    assert integrity["checked"] == 24


def test_probe_merchant_linkage_false_positive_control(tmp_path):
    """Probe 2: Unrelated buyers sharing only merchant_id do NOT form a suspicious cluster."""
    db_path = str(tmp_path / "probe2_audit.db")
    actions = []
    risk_scores = []
    cluster_sizes = []

    for i in range(10):
        dispute = {
            "dispute_id": f"MERCH_CLEAN_{i:02d}",
            "reason_code": "item_not_received",
            "amount": 2000.0,
            "merchant_id": "busy_merchant_xyz",
            "customer_id": f"unrelated_buyer_{i}",
            "card_fingerprint": f"card_tok_{i}",
            "device_id": f"dev_{i}",
            "ip_address": f"198.51.100.{10 + i}",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
        }
        res = decide_case(dispute, db_path=db_path, include_counterfactual=False)
        actions.append(res["action"])
        risk_scores.append(res["graph_analysis"]["risk_score"])
        cluster_sizes.append(res["graph_analysis"]["cluster_size"])

    for score in risk_scores:
        assert score == 0.0
    for size in cluster_sizes:
        assert size == 1
    for act in actions:
        assert act == "AUTO-CONTEST"


def test_probe_mutated_replay_dispute_id_conflict(monkeypatch, tmp_path):
    """Probe 3: Mutated payload for an existing dispute_id must be rejected with HTTP 409 Conflict."""
    db_path = str(tmp_path / "probe3_audit.db")
    monkeypatch.setenv("CHARGEBACK_ENV", "development")
    monkeypatch.setenv("CHARGEBACK_DB_PATH", db_path)
    monkeypatch.setenv("CHARGEBACK_AUDIT_DB_PATH", db_path)
    reset_settings()

    client = TestClient(app)
    payload_a = {
        "dispute_id": "REPLAY_CONFLICT_001",
        "payment_id": "pay_001",
        "reason_code": "item_not_received",
        "amount": 1500.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
    }
    resp1 = client.post("/decision", json=payload_a)
    assert resp1.status_code == 200

    payload_b = dict(payload_a)
    payload_b["amount"] = 8500.0
    resp2 = client.post("/decision", json=payload_b)
    assert resp2.status_code == 409
    assert "Conflict" in resp2.json()["detail"]


def test_probe_fail_field_hard_stop_in_evidence(tmp_path):
    """Probe 4: Any explicitly failing evidence field halts AUTO-CONTEST."""
    db_path = str(tmp_path / "probe4_audit.db")
    dispute = {
        "dispute_id": "FAIL_FIELD_001",
        "reason_code": "item_not_received",
        "amount": 3000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": False,
    }
    res = decide_case(dispute, db_path=db_path, include_counterfactual=False)
    assert res["action"] == "HUMAN-REVIEW"
    assert "has_signature_confirmation" in res["reason"]


def test_probe_shared_ip_damping_and_false_positive_threshold():
    """Probe 5: High-degree IP addresses are damped and alone do not exceed escalation threshold."""
    graph = RiskGraph()
    for i in range(10):
        graph.add(
            {
                "dispute_id": f"DISP_IP_{i:02d}",
                "customer_id": f"cust_ip_{i}",
                "ip_address": "192.0.2.1",
                "card_fingerprint": f"card_{i}",
                "device_id": f"device_{i}",
            }
        )
    analysis = graph.analyze(
        {
            "dispute_id": "DISP_IP_99",
            "customer_id": "cust_ip_99",
            "ip_address": "192.0.2.1",
            "card_fingerprint": "card_99",
            "device_id": "device_99",
        }
    )
    assert analysis.risk_score < GRAPH_ESCALATION_THRESHOLD
    assert analysis.risk_score <= 0.25


def test_probe_api_production_mode_auth_enforcement(monkeypatch):
    """Probe 6: Starting API in production mode without CHARGEBACK_API_KEY must raise RuntimeError."""
    monkeypatch.setenv("CHARGEBACK_ENV", "production")
    monkeypatch.delenv("CHARGEBACK_API_KEY", raising=False)
    monkeypatch.delenv("CHARGEBACK_API_KEYS", raising=False)
    reset_settings()

    with pytest.raises(RuntimeError):
        _validate_startup_config()


def test_probe_model_artifact_tamper_detection(tmp_path):
    """Probe 7: Tampering with model bytes fails sidecar integrity check."""
    model_path = str(tmp_path / "probe7_model.json")
    save_ml_scorer(path=model_path, train_csv="data/train.csv")

    with open(model_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    first_key = next(iter(data["models"]))
    data["models"][first_key]["intercept"][0] += 5.0
    with open(model_path, "wb") as f:
        f.write(json.dumps(data).encode("utf-8"))

    reset_cached_ml_scorer()
    with pytest.raises(ValueError, match="Model integrity failure"):
        load_or_fit_ml_scorer(path=model_path, train_csv="data/train.csv", reload=True)
