"""
test_integration.py — one true end-to-end integration test that walks
a dispute through every layer of the system in a single test, using
data that actually came out of the generator rather than a hand-crafted
dict:

    generate_data (hidden_truth.generate_one)
        -> scorer.predict_win_probability   (direct, for an independent expected value)
        -> evidence.assemble                (direct, for an independent expected value)
        -> policy.decide                    (direct, for an independent expected value)
        -> api.py's real /score endpoint     (the actual system under test)
        -> audit_log.py                      (persisted record + idempotent replay)

Every other test file in this suite tests one layer, or two adjacent
layers (test_local_pipeline.py's API cross-check, test_audit_log.py's
concurrency fuzz test). This file is the only place all six steps are
chained in one test, so a break in how any two layers are wired together
-- not just a break inside a single module -- would show up here.
"""

import os

import pytest
from fastapi.testclient import TestClient

from chargeback_risk_engine.hidden_truth import generate_one
import random

from chargeback_risk_engine.scorer import predict_win_probability
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from training.train_models import load_or_fit_tree_model, predict_model
from chargeback_risk_engine.engine.risk_model import combine_probabilities
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.policy import decide
from chargeback_risk_engine.audit_log import DB_PATH, get_existing_decision
from chargeback_risk_engine.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_audit_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def _generated_dispute_to_request(dispute_id: str, reason_code: str, amount: float) -> dict:
    """Builds a real API request payload from a GENERATED evidence dict
    (hidden_truth.generate_one output), the same way generate_data.py
    turns generator output into a CSV row -- would_win and the hidden
    variable are never included, matching what a real caller sends."""
    generated = generate_one(random.Random(2026), reason_code)
    request = {
        "dispute_id": dispute_id,
        "payment_id": "pay_integration_test",
        "reason_code": reason_code,
        "amount": amount,
        **generated.evidence,
    }
    return request, generated


def test_full_pipeline_from_generated_data_through_api_to_audit_log():
    reason_code = "item_not_received"
    amount = 4500.0
    dispute_id = "D_INTEGRATION_001"

    request_payload, generated = _generated_dispute_to_request(dispute_id, reason_code, amount)

    # --- Independent expected value: compute scorer -> evidence -> policy
    # directly, completely bypassing the API, so this test doesn't just
    # check "the API returns 200" but that its answer is the SAME answer
    # the already-tested pipeline modules would give for this exact,
    # generator-produced evidence. ---
    dispute_dict = {k: v for k, v in request_payload.items() if k not in ("dispute_id", "payment_id")}
    expected_rule = predict_win_probability(dispute_dict)
    expected_packet = assemble(dispute_dict)
    ml = load_or_fit_ml_scorer()
    tree_model, tree_columns = load_or_fit_tree_model()
    ml_dispute = {"reason_code": reason_code, **{
        item.field: {"PASS": True, "FAIL": False, "WARN": None}[item.status]
        for item in expected_packet.items
    }}
    expected_logistic = ml.predict_win_probability(ml_dispute)
    expected_tree = float(predict_model(tree_model, tree_columns, __import__("pandas").DataFrame([dispute_dict]))[0])
    expected_probability = combine_probabilities(rules=expected_rule, logistic=expected_logistic, tree=expected_tree)
    expected_decision = decide(
        win_probability=expected_probability,
        amount=amount,
        evidence_packet=expected_packet,
    )

    # --- Step through the real HTTP API (the only place this suite calls
    # the full FastAPI app for a dispute built from GENERATED evidence,
    # not a hand-picked example). ---
    response = client.post("/score", json=request_payload)
    assert response.status_code == 200
    data = response.json()

    assert data["win_probability"] == pytest.approx(expected_probability)
    assert data["action"] == expected_decision.action
    assert data["expected_value"] == pytest.approx(expected_decision.expected_value)
    assert data["replayed"] is False

    # --- Calibration: a second, informational probability that must sit
    # alongside the decision without having driven it -- the action above
    # was already decided from the raw (uncalibrated) probability. ---
    from chargeback_risk_engine.calibration import apply_calibration, load_or_fit_calibration_points
    expected_calibrated = apply_calibration(load_or_fit_calibration_points(), expected_probability)
    assert data["calibrated_win_probability"] == pytest.approx(expected_calibrated)

    # --- Third probability: the trained ML scorer's own live estimate,
    # also purely informational -- reconstructed from the same evidence
    # the API just persisted, so it must match calling the model directly. ---
    from chargeback_risk_engine.ml_scorer import dispute_from_evidence_items
    ml_scorer_instance = load_or_fit_ml_scorer()
    ml_dispute = dispute_from_evidence_items(reason_code, data["evidence"])
    expected_ml_probability = ml_scorer_instance.predict_win_probability(ml_dispute)
    assert data["ml_win_probability"] == pytest.approx(expected_ml_probability)

    api_statuses = {item["field"]: item["status"] for item in data["evidence"]}
    expected_statuses = {item.field: item.status for item in expected_packet.items}
    assert api_statuses == expected_statuses

    # --- Razorpay adapter: an AUTO-CONTEST decision must come with a
    # ready-to-review draft in Razorpay's real evidence-submission shape,
    # and that draft must always say "draft", never "submit". ---
    if data["action"] == "AUTO-CONTEST":
        assert data["contest_draft"] is not None
        assert data["contest_draft"]["action"] == "draft"
    else:
        assert data["contest_draft"] is None

    # --- Audit trail: the decision the API just made must be durably
    # persisted under this dispute_id, independently readable via a
    # fresh connection (simulating a server restart / separate process). ---
    logged = get_existing_decision(dispute_id)
    assert logged is not None
    assert logged.action == data["action"]
    assert logged.win_probability == pytest.approx(data["win_probability"])
    assert logged.reason_code == reason_code
    assert logged.amount == amount

    # --- Idempotency closes the loop: resubmitting the same dispute_id
    # through the real API a second time must replay the persisted
    # decision, not recompute -- even though nothing stops a caller from
    # sending different evidence the second time around. ---
    mutated_payload = dict(request_payload)
    mutated_payload["has_tracking_number"] = not dispute_dict.get("has_tracking_number", False)
    replay_response = client.post("/score", json=mutated_payload)
    assert replay_response.status_code == 200
    replay_data = replay_response.json()

    assert replay_data["replayed"] is True
    assert replay_data["action"] == data["action"]
    assert replay_data["win_probability"] == data["win_probability"]
    assert replay_data["calibrated_win_probability"] == data["calibrated_win_probability"]
    assert replay_data["ml_win_probability"] == data["ml_win_probability"]
    assert replay_data["expected_value"] == data["expected_value"]
    assert replay_data["contest_draft"] == data["contest_draft"]


def test_full_pipeline_over_ceiling_generated_dispute_never_auto_contests():
    """Same six-layer chain, but for a generated dispute whose amount is
    deliberately pushed over MONETARY_CEILING -- proving the safety
    property holds through the full stack, not just in policy.py's own
    unit tests, for data that came from the generator rather than a
    hand-picked dict."""
    from chargeback_risk_engine.policy import MONETARY_CEILING

    reason_code = "unauthorized_transaction"
    amount = MONETARY_CEILING + 12_345.0
    dispute_id = "D_INTEGRATION_CEILING_001"

    request_payload, _ = _generated_dispute_to_request(dispute_id, reason_code, amount)

    response = client.post("/score", json=request_payload)
    assert response.status_code == 200
    data = response.json()

    assert data["action"] == "HUMAN REVIEW"
    assert "ceiling" in data["reason"].lower()
    assert data["contest_draft"] is None
    # The ceiling blocks the ACTION, not the informational probabilities --
    # both are still computed and returned even when routed to a human.
    assert 0.0 <= data["calibrated_win_probability"] <= 1.0
    assert 0.0 <= data["ml_win_probability"] <= 1.0

    logged = get_existing_decision(dispute_id)
    assert logged is not None
    assert logged.action == "HUMAN REVIEW"
