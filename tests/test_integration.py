import os
import random

import pytest
from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app
from chargeback_risk_engine.audit_log import DB_PATH, get_existing_decision
from chargeback_risk_engine.synthetic_ground_truth import generate_one
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.engine.evidence_score import score_evidence

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_audit_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def _generated_request(dispute_id: str, reason_code: str, amount: float) -> dict:
    generated = generate_one(random.Random(2026), reason_code)
    return {
        "dispute_id": dispute_id,
        "payment_id": "pay_integration_test",
        "reason_code": reason_code,
        "amount": amount,
        **generated.evidence,
    }


def test_generated_case_matches_live_model_and_audit_round_trip():
    reason_code = "item_not_received"
    request = _generated_request("D_INTEGRATION_001", reason_code, 4500.0)
    response = client.post("/decision", json=request)
    assert response.status_code == 200
    data = response.json()

    dispute = {k: v for k, v in request.items() if k not in {"dispute_id", "payment_id"}}
    packet = assemble(dispute)
    quality = score_evidence(dispute, packet)
    scorer = load_or_fit_ml_scorer()
    expected_probability = scorer.predict_win_probability(dispute)

    assert data["win_probability"] == pytest.approx(expected_probability)
    assert {x["field"]: x["status"] for x in data["evidence"]} == {
        x.field: x.status for x in packet.items
    }
    assert data["evidence_score"]["completeness"] == pytest.approx(quality.completeness)
    assert data["model_version"] == data["live_model"]
    assert data["replayed"] is False

    logged = get_existing_decision("D_INTEGRATION_001")
    assert logged is not None
    assert logged.action == data["action"]
    assert logged.win_probability == pytest.approx(data["win_probability"])

    mutated = dict(request)
    mutated["amount"] = 9999
    mutated["has_tracking_number"] = False
    replay = client.post("/decision", json=mutated).json()
    assert replay["replayed"] is True
    assert replay["amount"] == data["amount"]
    assert replay["win_probability"] == data["win_probability"]
    assert replay["action"] == data["action"]
    assert replay["counterfactual"] == data["counterfactual"]


def test_generated_over_ceiling_case_never_auto_contests():
    from chargeback_risk_engine.policy import MONETARY_CEILING

    request = _generated_request(
        "D_INTEGRATION_CEILING_001",
        "unauthorized_transaction",
        MONETARY_CEILING + 12_345.0,
    )
    data = client.post("/decision", json=request).json()
    assert data["action"] == "HUMAN-REVIEW"
    assert "ceiling" in data["reason"].lower()
    assert data["contest_draft"] is None
