"""
scorer.py — interpretable, rule-based, reason-code-aware scorer.

Start with an interpretable rule-based scorer. Only add ML later if it
measurably beats this. Evidence irrelevant to a dispute's reason_code
must never affect its score -- enforced structurally here by only ever
reading RELEVANT_EVIDENCE_BY_REASON[reason_code], nothing else.
"""

import math

from config import RELEVANT_EVIDENCE_BY_REASON

# How much each relevant field's True/False shifts the raw score.
# Equal weight for now (interpretable, easy to defend) -- a real project
# could hand-tune these per field if evidence, but equal weight is the
# honest starting point.
FIELD_WEIGHT = 1.0


def raw_score(dispute: dict) -> float:
    """
    Sum of weighted votes from RELEVANT evidence fields only.
    True -> +weight, False -> -weight, None (unknown) -> 0 (neutral).
    """
    relevant_fields = RELEVANT_EVIDENCE_BY_REASON[dispute["reason_code"]]
    total = 0.0
    for field_name in relevant_fields:
        value = dispute.get(field_name)
        if value is True:
            total += FIELD_WEIGHT
        elif value is False:
            total -= FIELD_WEIGHT
        # None -> no change, deliberately
    return total


def score_to_probability(score: float, n_relevant_fields: int) -> float:
    """
    Turn a raw score into a probability estimate via a logistic squashing
    function. Centered at 0.5 when score=0 (no evidence either way).
    Scaled by the number of relevant fields so a reason code with more
    fields doesn't automatically produce more extreme probabilities.
    """
    if n_relevant_fields == 0:
        return 0.5
    # Normalize score to roughly [-1, 1] range based on max possible score
    normalized = score / n_relevant_fields
    # Logistic squash: k controls how sharply probability moves per unit
    # of normalized score. k=2.5 chosen so a fully-positive dispute lands
    # around 0.92, fully-negative around 0.08 -- confident but not 0/1.
    k = 2.5
    probability = 1.0 / (1.0 + math.exp(-k * normalized))
    return probability


def predict_win_probability(dispute: dict) -> float:
    relevant_fields = RELEVANT_EVIDENCE_BY_REASON[dispute["reason_code"]]
    score = raw_score(dispute)
    return score_to_probability(score, len(relevant_fields))