"""
test_generator.py — real, runnable tests for hidden_truth.py and
generate_data.py. Asserts, in code, the properties the generator is
supposed to guarantee -- not just prose in a design note.
"""

import random

import pytest

from chargeback_risk_engine.config import ALL_EVIDENCE_FIELDS, RELEVANT_EVIDENCE_BY_REASON, REASON_CODES
from scripts.generate_data import generate_dataset, CSV_COLUMNS
from chargeback_risk_engine.hidden_truth import generate_one, MISSINGNESS_RATE


def test_would_win_rate_is_sane():
    """would_win should be neither ~0% nor ~100% -- a learnable, non-trivial rate."""
    rng = random.Random(42)
    results = [generate_one(rng, rng.choice(REASON_CODES)) for _ in range(3000)]
    win_rate = sum(r.would_win for r in results) / len(results)
    assert 0.30 < win_rate < 0.80, f"would_win rate {win_rate:.1%} is suspicious (too extreme)"


def test_hidden_variable_never_in_dataset_output():
    """generate_dataset()'s output rows must NOT contain hidden_seller_legitimate
    or any key starting with '_' -- the scorer must never be able to see it."""
    rows = generate_dataset(n=200, seed=1)
    for row in rows:
        assert set(row.keys()) == set(CSV_COLUMNS), (
            f"row has unexpected keys: {set(row.keys()) - set(CSV_COLUMNS)}"
        )
        assert "hidden_seller_legitimate" not in row
        assert not any(k.startswith("_") for k in row.keys())


def test_generation_is_reproducible_with_same_seed():
    """Same seed -> byte-for-byte identical dataset."""
    rows_a = generate_dataset(n=100, seed=7)
    rows_b = generate_dataset(n=100, seed=7)
    assert rows_a == rows_b


def test_generation_differs_with_different_seed():
    """Sanity check the seed is actually doing something."""
    rows_a = generate_dataset(n=100, seed=7)
    rows_b = generate_dataset(n=100, seed=8)
    assert rows_a != rows_b


def test_missingness_rate_roughly_matches_config():
    """Observed None rate across evidence fields should be close to
    MISSINGNESS_RATE (within a reasonable tolerance for sampling noise)."""
    rows = generate_dataset(n=5000, seed=42)
    total_values = 0
    none_values = 0
    for row in rows:
        for field_name in ALL_EVIDENCE_FIELDS:
            total_values += 1
            if row[field_name] in (None, ""):
                none_values += 1
    observed_rate = none_values / total_values
    assert abs(observed_rate - MISSINGNESS_RATE) < 0.03, (
        f"observed missingness {observed_rate:.1%} too far from configured {MISSINGNESS_RATE:.1%}"
    )


def test_relevant_fields_correlate_more_than_irrelevant_fields():
    """For each reason code, the true-rate of a RELEVANT field, split by
    would_win, should differ more than an IRRELEVANT field's true-rate
    split by would_win. This is a sanity check that the generator's
    reason-code-aware logic is actually doing something, not a no-op."""
    rows = generate_dataset(n=6000, seed=42)

    for reason in REASON_CODES:
        reason_rows = [r for r in rows if r["reason_code"] == reason]
        relevant = RELEVANT_EVIDENCE_BY_REASON[reason]
        irrelevant = [f for f in ALL_EVIDENCE_FIELDS if f not in relevant]

        def true_rate_gap(field_name):
            wins = [r for r in reason_rows if r["would_win"] and r[field_name] is not None]
            losses = [r for r in reason_rows if not r["would_win"] and r[field_name] is not None]
            if not wins or not losses:
                return 0.0
            win_rate = sum(1 for r in wins if r[field_name]) / len(wins)
            loss_rate = sum(1 for r in losses if r[field_name]) / len(losses)
            return abs(win_rate - loss_rate)

        relevant_gaps = [true_rate_gap(f) for f in relevant]
        irrelevant_gaps = [true_rate_gap(f) for f in irrelevant]

        avg_relevant_gap = sum(relevant_gaps) / len(relevant_gaps)
        avg_irrelevant_gap = sum(irrelevant_gaps) / len(irrelevant_gaps)

        assert avg_relevant_gap > avg_irrelevant_gap, (
            f"{reason}: relevant fields' win/loss gap ({avg_relevant_gap:.3f}) "
            f"should exceed irrelevant fields' gap ({avg_irrelevant_gap:.3f})"
        )