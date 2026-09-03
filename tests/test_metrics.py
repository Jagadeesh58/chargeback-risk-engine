"""
test_metrics.py — real, runnable tests for metrics.py.
"""

import pandas as pd

from chargeback_risk_engine.metrics import (
    run_pipeline,
    confusion_matrix_for_auto_contest,
    precision_recall_f1,
    false_positive_cost,
    calibration_check,
)


def test_confusion_matrix_counts_sum_to_total_rows():
    test = pd.read_csv("data/test.csv")
    results = run_pipeline(test)
    cm = confusion_matrix_for_auto_contest(results)
    total = cm["true_positive"] + cm["false_positive"] + cm["true_negative"] + cm["false_negative"]
    assert total == len(results)


def test_precision_and_recall_are_valid_fractions():
    test = pd.read_csv("data/test.csv")
    results = run_pipeline(test)
    cm = confusion_matrix_for_auto_contest(results)
    prf = precision_recall_f1(cm)
    assert 0.0 <= prf["precision"] <= 1.0
    assert 0.0 <= prf["recall"] <= 1.0
    assert 0.0 <= prf["f1"] <= 1.0


def test_precision_beats_naive_would_win_rate():
    """A useful scorer's precision on AUTO-CONTEST calls should beat just
    guessing 'win' for everyone (the raw would_win rate in the data)."""
    test = pd.read_csv("data/test.csv")
    results = run_pipeline(test)
    cm = confusion_matrix_for_auto_contest(results)
    prf = precision_recall_f1(cm)
    naive_rate = test["would_win"].mean()
    assert prf["precision"] > naive_rate, (
        f"AUTO-CONTEST precision {prf['precision']:.3f} should beat "
        f"the naive would_win rate {naive_rate:.3f}"
    )


def test_false_positive_cost_is_nonnegative():
    test = pd.read_csv("data/test.csv")
    results = run_pipeline(test)
    cost = false_positive_cost(results)
    assert cost >= 0.0


def test_false_positive_cost_only_counts_actual_false_positives():
    """Sanity check: cost should be zero if there are no false positives."""
    fake_results = pd.DataFrame({
        "action": ["AUTO-CONTEST", "AUTO-CONTEST"],
        "would_win": [True, True],
        "amount": [1000.0, 2000.0],
    })
    cost = false_positive_cost(fake_results)
    assert cost == 0.0


def test_calibration_check_bins_cover_all_rows():
    test = pd.read_csv("data/test.csv")
    results = run_pipeline(test)
    calibration = calibration_check(results, n_bins=5)
    assert calibration["count"].sum() == len(results)


def test_calibration_actual_rate_is_valid_fraction_per_bin():
    test = pd.read_csv("data/test.csv")
    results = run_pipeline(test)
    calibration = calibration_check(results, n_bins=5)
    assert (calibration["actual_win_rate"] >= 0.0).all()
    assert (calibration["actual_win_rate"] <= 1.0).all()