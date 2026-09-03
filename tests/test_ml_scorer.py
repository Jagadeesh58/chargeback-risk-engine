"""
test_ml_scorer.py — real, runnable tests for ml_scorer.py.
"""

import os

import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from chargeback_risk_engine.ml_scorer import (
    MLScorer,
    dispute_from_evidence_items,
    evaluate_on,
    load_or_fit_ml_scorer,
)
from chargeback_risk_engine.scorer import predict_win_probability
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.metrics import _row_to_dispute
from chargeback_risk_engine.config import REASON_CODES

TEST_MODEL_PATH = "test_ml_scorer_model_pytest.pkl"


@pytest.fixture(autouse=True)
def clean_model_file():
    if os.path.exists(TEST_MODEL_PATH):
        os.remove(TEST_MODEL_PATH)
    import chargeback_risk_engine.ml_scorer as ml_scorer
    ml_scorer._cached_scorer = None
    yield
    if os.path.exists(TEST_MODEL_PATH):
        os.remove(TEST_MODEL_PATH)
    ml_scorer._cached_scorer = None


def test_ml_scorer_trains_one_model_per_reason_code():
    train = pd.read_csv("data/train.csv")
    ml = MLScorer().fit(train)
    assert set(ml.models.keys()) == set(REASON_CODES)


def test_ml_scorer_output_is_valid_probability():
    train = pd.read_csv("data/train.csv")
    ml = MLScorer().fit(train)
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": None,
    }
    p = ml.predict_win_probability(dispute)
    assert 0.0 <= p <= 1.0


def test_ml_scorer_auc_beats_random_on_test_set():
    train = pd.read_csv("data/train.csv")
    test = pd.read_csv("data/test.csv")
    ml = MLScorer().fit(train)
    auc = evaluate_on(test, ml)
    assert auc > 0.55


def test_ml_scorer_does_not_dramatically_beat_rule_based_scorer():
    """
    The trained ML scorer's AUC on test.csv should be very close to the
    rule-based scorer's AUC -- NOT dramatically
    better -- because the synthetic generator gives every relevant field
    equal correlation strength by design (see hidden_truth.py), so there
    is no hidden per-field weighting pattern for ML to discover.
    If this test ever fails because ML suddenly does dramatically better,
    that's worth investigating -- it could mean the generator changed.
    """
    train = pd.read_csv("data/train.csv")
    test = pd.read_csv("data/test.csv")

    ml = MLScorer().fit(train)
    ml_auc = evaluate_on(test, ml)

    rule_probs = []
    for _, row in test.iterrows():
        dispute = _row_to_dispute(row)
        rule_probs.append(predict_win_probability(dispute))
    rule_auc = roc_auc_score(test["would_win"], rule_probs)

    assert abs(ml_auc - rule_auc) < 0.03, (
        f"Expected ML AUC ({ml_auc:.4f}) to be close to rule-based AUC "
        f"({rule_auc:.4f}) given the generator's equal field-strength design"
    )


def test_ml_scorer_learned_weights_are_roughly_equal_per_reason():
    """
    Verifies the actual mechanism behind the AUC tie: the learned
    coefficients for each reason code's relevant fields should be
    roughly similar to each other, confirming the ML model independently
    discovered near-equal field importance -- matching our hand-picked
    equal weighting in scorer.py.
    """
    train = pd.read_csv("data/train.csv")
    ml = MLScorer().fit(train)

    for reason in REASON_CODES:
        coefs = ml.models[reason].coef_[0]
        spread = max(coefs) - min(coefs)
        assert spread < 0.5, (
            f"{reason}: learned coefficients {coefs} have spread {spread:.3f}, "
            f"expected them to be roughly equal given the generator's design"
        )


def test_dispute_from_evidence_items_reconstructs_true_false_none():
    evidence_items = [
        {"field": "has_tracking_number", "status": "PASS"},
        {"field": "has_delivery_confirmation", "status": "FAIL"},
        {"field": "has_signature_confirmation", "status": "WARN"},
    ]
    dispute = dispute_from_evidence_items("item_not_received", evidence_items)
    assert dispute["reason_code"] == "item_not_received"
    assert dispute["has_tracking_number"] is True
    assert dispute["has_delivery_confirmation"] is False
    assert dispute["has_signature_confirmation"] is None


def test_dispute_from_evidence_items_matches_assemble_round_trip():
    """The reconstruction must exactly invert evidence.assemble() -- a
    dispute assembled into a packet and reconstructed back should
    produce the same True/False/None values it started with."""
    original = {
        "reason_code": "duplicate_charge",
        "has_duplicate_transaction_proof": True,
        "has_refund_already_issued": False,
    }
    packet = assemble(original)
    evidence_items = [{"field": i.field, "status": i.status} for i in packet.items]
    reconstructed = dispute_from_evidence_items("duplicate_charge", evidence_items)
    assert reconstructed["has_duplicate_transaction_proof"] is True
    assert reconstructed["has_refund_already_issued"] is False


def test_load_or_fit_ml_scorer_trains_and_caches():
    scorer = load_or_fit_ml_scorer(path=TEST_MODEL_PATH, train_csv="data/train.csv")
    assert set(scorer.models.keys()) == set(REASON_CODES)
    assert os.path.exists(TEST_MODEL_PATH)

    second = load_or_fit_ml_scorer(path=TEST_MODEL_PATH, train_csv="data/train.csv")
    assert second is scorer  # in-process cache, not refit


def test_load_or_fit_ml_scorer_reloads_from_saved_file():
    """A fresh call after clearing the in-process cache should load the
    pickled model from disk rather than retraining, and produce the
    same prediction as the original."""
    import chargeback_risk_engine.ml_scorer as ml_scorer_module

    first = load_or_fit_ml_scorer(path=TEST_MODEL_PATH, train_csv="data/train.csv")
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    first_prediction = first.predict_win_probability(dispute)

    ml_scorer_module._cached_scorer = None  # simulate a fresh process
    reloaded = load_or_fit_ml_scorer(path=TEST_MODEL_PATH, train_csv="data/train.csv")
    assert reloaded.predict_win_probability(dispute) == first_prediction