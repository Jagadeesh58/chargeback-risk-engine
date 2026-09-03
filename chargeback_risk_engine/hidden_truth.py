"""
hidden_truth.py — THE ONLY place `would_win` gets decided.

Design:
- would_win is generated from a HIDDEN variable (hidden_seller_legitimate)
  that the scorer never sees.
- Evidence fields RELEVANT to a dispute's reason code are noisy proxies
  for the hidden variable (correlated, not identical).
- Evidence fields IRRELEVANT to a dispute's reason code are generated
  independently of the hidden variable -- they carry no real signal for
  that dispute, on purpose (this is what the "irrelevant evidence must
  not affect the score" test checks downstream).
- Every evidence field also has: occasional contradiction (a small chance
  the "relevant" field is flipped against the hidden truth anyway) and
  missingness (a chance the field is None instead of True/False).

IMPORTANT: generate_data.py (which builds the CSV the scorer trains/tests
on) must NOT import hidden_seller_legitimate or store it anywhere the
scorer can read. It's returned here only for our own empirical
verification of the generator itself.
"""

import random
from dataclasses import dataclass

from chargeback_risk_engine.config import ALL_EVIDENCE_FIELDS, RELEVANT_EVIDENCE_BY_REASON

# --- Tunable parameters, all in one place for later sensitivity checks ---
HIDDEN_LEGIT_BASE_RATE = 0.60          # P(hidden_seller_legitimate = True)
WIN_RATE_IF_LEGIT = 0.82               # P(would_win | legitimate)
WIN_RATE_IF_NOT_LEGIT = 0.18           # P(would_win | not legitimate)

RELEVANT_FIELD_RATE_IF_LEGIT = 0.78    # P(relevant evidence True | legit)
RELEVANT_FIELD_RATE_IF_NOT_LEGIT = 0.30  # P(relevant evidence True | not legit)
IRRELEVANT_FIELD_RATE = 0.50           # P(irrelevant evidence True), no dependence on hidden truth

CONTRADICTION_RATE = 0.08              # chance a relevant field is flipped anyway
MISSINGNESS_RATE = 0.15                # chance any evidence field is None


def _sample_bool(rng: random.Random, p: float) -> bool:
    return rng.random() < p


@dataclass
class HiddenTruthResult:
    reason_code: str
    hidden_seller_legitimate: bool   # NEVER exposed to the scorer
    would_win: bool
    evidence: dict[str, bool | None]


def generate_one(rng: random.Random, reason_code: str) -> HiddenTruthResult:
    relevant_fields = set(RELEVANT_EVIDENCE_BY_REASON[reason_code])

    hidden_legit = _sample_bool(rng, HIDDEN_LEGIT_BASE_RATE)
    would_win = _sample_bool(
        rng, WIN_RATE_IF_LEGIT if hidden_legit else WIN_RATE_IF_NOT_LEGIT
    )

    evidence: dict[str, bool | None] = {}
    for field_name in ALL_EVIDENCE_FIELDS:
        if field_name in relevant_fields:
            base_rate = (
                RELEVANT_FIELD_RATE_IF_LEGIT
                if hidden_legit
                else RELEVANT_FIELD_RATE_IF_NOT_LEGIT
            )
            value = _sample_bool(rng, base_rate)
            # occasional contradiction: flip it anyway, independent of truth
            if _sample_bool(rng, CONTRADICTION_RATE):
                value = not value
        else:
            # irrelevant to this reason code: no dependence on hidden truth
            value = _sample_bool(rng, IRRELEVANT_FIELD_RATE)

        # missingness applies to every field, relevant or not
        if _sample_bool(rng, MISSINGNESS_RATE):
            value = None

        evidence[field_name] = value

    return HiddenTruthResult(
        reason_code=reason_code,
        hidden_seller_legitimate=hidden_legit,
        would_win=would_win,
        evidence=evidence,
    )
