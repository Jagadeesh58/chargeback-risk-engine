"""
test_baseline.py — real, runnable tests for baseline.py.
Uses a tiny 5-dispute example verified BY HAND first (see MISTAKES.md /
chat history), so these expected values are independently trustworthy,
not just "whatever the code outputs".
"""

import pandas as pd

from baseline import run_naive_baseline


def _tiny_dataset():
    return pd.DataFrame({
        "amount": [1000, 2000, 500, 3000, 1500],
        "would_win": [True, False, True, False, True],
    })


def test_precision_matches_hand_calculation():
    result = run_naive_baseline(_tiny_dataset())
    assert result["precision"] == 0.6


def test_recall_is_always_100_percent():
    """Contesting everything can never miss a winner -- recall must
    always be exactly 1.0, regardless of the data."""
    result = run_naive_baseline(_tiny_dataset())
    assert result["recall"] == 1.0


def test_false_positive_cost_matches_hand_calculation():
    result = run_naive_baseline(_tiny_dataset())
    # 2 losses (disputes 2 and 4) x 150 contest fee each -- NOT + amount,
    # since the disputed amount was already gone via the chargeback
    # regardless of the contest decision (matches policy.py's EV model).
    assert result["false_positive_cost"] == 300.0


def test_false_positive_count_matches_actual_losses():
    result = run_naive_baseline(_tiny_dataset())
    assert result["false_positive_count"] == 2  # disputes 2 and 4 lost


def test_all_wins_means_perfect_precision():
    """Sanity check: if every dispute would win, precision should be 1.0."""
    all_wins = pd.DataFrame({"amount": [100, 200], "would_win": [True, True]})
    result = run_naive_baseline(all_wins)
    assert result["precision"] == 1.0
    assert result["false_positive_cost"] == 0.0


def test_all_losses_means_zero_precision():
    """Sanity check: if every dispute would lose, precision should be 0.0."""
    all_losses = pd.DataFrame({"amount": [100, 200], "would_win": [False, False]})
    result = run_naive_baseline(all_losses)
    assert result["precision"] == 0.0


def test_baseline_on_real_test_set_matches_would_win_rate():
    """The naive baseline's precision on the real test.csv should exactly
    equal the raw would_win rate, since it's contesting everything."""
    test = pd.read_csv("test.csv")
    result = run_naive_baseline(test)
    assert abs(result["precision"] - test["would_win"].mean()) < 0.0001