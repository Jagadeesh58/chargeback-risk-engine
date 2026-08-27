"""
test_sensitivity.py — real, runnable tests for sensitivity.py.
"""

import pandas as pd

from sensitivity import sweep_auto_contest_threshold, sweep_monetary_ceiling


def test_higher_threshold_never_increases_auto_contest_count():
    """Raising the threshold can only keep the same or fewer disputes
    eligible for auto-contest -- never more."""
    test = pd.read_csv("test.csv")
    result = sweep_auto_contest_threshold(test, [0.5, 0.6, 0.7, 0.8, 0.9])
    counts = result["auto_contest_count"].tolist()
    assert all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1)), (
        f"auto_contest_count should be non-increasing as threshold rises: {counts}"
    )


def test_higher_threshold_never_decreases_precision():
    """Being stricter about which disputes to auto-contest should never
    make precision worse -- it should stay the same or improve."""
    test = pd.read_csv("test.csv")
    result = sweep_auto_contest_threshold(test, [0.5, 0.6, 0.7, 0.8, 0.9])
    precisions = result["precision"].tolist()
    # allow tiny floating point wiggle
    assert all(precisions[i] <= precisions[i + 1] + 0.001 for i in range(len(precisions) - 1)), (
        f"precision should be non-decreasing as threshold rises: {precisions}"
    )


def test_higher_threshold_never_increases_recall():
    test = pd.read_csv("test.csv")
    result = sweep_auto_contest_threshold(test, [0.5, 0.6, 0.7, 0.8, 0.9])
    recalls = result["recall"].tolist()
    assert all(recalls[i] >= recalls[i + 1] - 0.001 for i in range(len(recalls) - 1)), (
        f"recall should be non-increasing as threshold rises: {recalls}"
    )


def test_default_threshold_matches_checkpoint_5_metrics():
    """Sanity check: sweeping at exactly our real policy's threshold (0.65)
    should reproduce the same precision/recall we already measured in
    Checkpoint 5's metrics.py on the real test set."""
    test = pd.read_csv("test.csv")
    result = sweep_auto_contest_threshold(test, [0.65])
    row = result.iloc[0]
    assert abs(row["precision"] - 0.703) < 0.01
    assert abs(row["recall"] - 0.569) < 0.01


def test_higher_ceiling_never_decreases_auto_contest_count():
    """A higher ceiling can only let the same or more disputes through
    (fewer forced to human review for being too large) -- never fewer."""
    test = pd.read_csv("test.csv")
    result = sweep_monetary_ceiling(test, [5000, 25000, 100000, 1_000_000])
    counts = result["auto_contest_count"].tolist()
    assert all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1)), (
        f"auto_contest_count should be non-decreasing as ceiling rises: {counts}"
    )


def test_very_high_ceiling_stops_changing_results():
    """Once the ceiling is above every dispute amount in the data, raising
    it further should have zero effect -- a real, testable plateau."""
    test = pd.read_csv("test.csv")
    max_amount = test["amount"].max()
    result = sweep_monetary_ceiling(test, [max_amount + 1, max_amount + 1_000_000])
    assert result.iloc[0]["auto_contest_count"] == result.iloc[1]["auto_contest_count"]
    assert result.iloc[0]["precision"] == result.iloc[1]["precision"]