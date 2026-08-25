"""
test_scorer.py — real, runnable tests for scorer.py.
"""

import pandas as pd
from sklearn.metrics import roc_auc_score

from scorer import predict_win_probability, raw_score
from config import RELEVANT_EVIDENCE_BY_REASON, ALL_EVIDENCE_FIELDS, REASON_CODES


def test_irrelevant_evidence_does_not_affect_score():
    """Core principle #7 requirement: evidence irrelevant to a dispute's
    reason_code must not change its score, no matter what value it holds."""
    for reason in REASON_CODES:
        relevant = RELEVANT_EVIDENCE_BY_REASON[reason]
        irrelevant = [f for f in ALL_EVIDENCE_FIELDS if f not in relevant]

        base = {"reason_code": reason}
        for f in relevant:
            base[f] = True  # fix relevant evidence identically in both cases

        dispute_a = dict(base)
        dispute_b = dict(base)
        for f in irrelevant:
            dispute_a[f] = False
            dispute_b[f] = True

        score_a = predict_win_probability(dispute_a)
        score_b = predict_win_probability(dispute_b)
        assert score_a == score_b, (
            f"{reason}: irrelevant evidence changed the score ({score_a} != {score_b})"
        )


def test_all_true_scores_higher_than_all_false():
    """Sanity check: more positive relevant evidence should mean a higher score."""
    for reason in REASON_CODES:
        relevant = RELEVANT_EVIDENCE_BY_REASON[reason]
        strong = {"reason_code": reason, **{f: True for f in relevant}}
        weak = {"reason_code": reason, **{f: False for f in relevant}}
        assert predict_win_probability(strong) > predict_win_probability(weak)


def test_unknown_evidence_is_neutral():
    """All-None relevant evidence should produce exactly 0.5 -- no signal
    either way, per the missingness design from Checkpoint 1."""
    for reason in REASON_CODES:
        relevant = RELEVANT_EVIDENCE_BY_REASON[reason]
        dispute = {"reason_code": reason, **{f: None for f in relevant}}
        assert predict_win_probability(dispute) == 0.5


def test_probability_is_in_valid_range():
    """Output must always be a valid probability."""
    for reason in REASON_CODES:
        relevant = RELEVANT_EVIDENCE_BY_REASON[reason]
        for combo_value in (True, False, None):
            dispute = {"reason_code": reason, **{f: combo_value for f in relevant}}
            p = predict_win_probability(dispute)
            assert 0.0 <= p <= 1.0


def test_scorer_auc_on_dev_beats_random():
    """The scorer should measurably beat a coin flip (AUC > 0.5) on the
    actual held-out dev set -- not just on hand-built toy examples."""
    dev = pd.read_csv("dev.csv")
    probs = []
    for _, row in dev.iterrows():
        dispute = row.to_dict()
        for k, v in dispute.items():
            if isinstance(v, float) and pd.isna(v):
                dispute[k] = None
        probs.append(predict_win_probability(dispute))
    auc = roc_auc_score(dev["would_win"], probs)
    assert auc > 0.55, f"scorer AUC {auc:.3f} is too close to random guessing"