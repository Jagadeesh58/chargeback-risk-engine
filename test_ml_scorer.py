"""
test_ml_scorer.py — real, runnable tests for ml_scorer.py.
"""

import pandas as pd
from sklearn.metrics import roc_auc_score

from ml_scorer import MLScorer, evaluate_on
from scorer import predict_win_probability
from metrics import _row_to_dispute
from config import REASON_CODES


def test_ml_scorer_trains_one_model_per_reason_code():
    train = pd.read_csv("train.csv")
    ml = MLScorer().fit(train)
    assert set(ml.models.keys()) == set(REASON_CODES)


def test_ml_scorer_output_is_valid_probability():
    train = pd.read_csv("train.csv")
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
    train = pd.read_csv("train.csv")
    test = pd.read_csv("test.csv")
    ml = MLScorer().fit(train)
    auc = evaluate_on(test, ml)
    assert auc > 0.55


def test_ml_scorer_does_not_dramatically_beat_rule_based_scorer():
    """
    Checkpoint 8 finding: the trained ML scorer's AUC on test.csv should
    be very close to the rule-based scorer's AUC -- NOT dramatically
    better -- because the synthetic generator gives every relevant field
    equal correlation strength by design (see hidden_truth.py), so there
    is no hidden per-field weighting pattern for ML to discover.
    If this test ever fails because ML suddenly does dramatically better,
    that's worth investigating -- it could mean the generator changed.
    """
    train = pd.read_csv("train.csv")
    test = pd.read_csv("test.csv")

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
    train = pd.read_csv("train.csv")
    ml = MLScorer().fit(train)

    for reason in REASON_CODES:
        coefs = ml.models[reason].coef_[0]
        spread = max(coefs) - min(coefs)
        assert spread < 0.5, (
            f"{reason}: learned coefficients {coefs} have spread {spread:.3f}, "
            f"expected them to be roughly equal given the generator's design"
        )