"""
baseline.py — the naive "contest everything" baseline, compared
honestly against the real scorer+evidence+policy pipeline on the same
held-out test set. Per Checkpoint 6: proves (or disproves) that the
pipeline's added complexity is actually earning its keep.
"""

import pandas as pd


def run_naive_baseline(df: pd.DataFrame, contest_cost: float = 150.0) -> dict:
    """
    Simulates contesting every single dispute, no scoring, no policy.
    Returns the same style of metrics as the real pipeline for direct
    comparison.
    """
    total = len(df)
    wins = df["would_win"].sum()
    losses = total - wins

    # Precision: contest everything -> precision = overall would_win rate
    precision = wins / total if total > 0 else 0.0
    # Recall: contest everything -> we catch every winnable dispute -> 100%
    recall = 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # False-positive cost: every LOST dispute we contested costs the fee
    # plus the amount itself.
    lost_disputes = df[df["would_win"] == False]
    fp_cost = float((lost_disputes["amount"] + contest_cost).sum())

    # Total money recovered from WON contests, for a fuller picture
    won_disputes = df[df["would_win"] == True]
    money_recovered = float(won_disputes["amount"].sum()) - (total * contest_cost)

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_cost": fp_cost,
        "false_positive_count": int(losses),
        "net_money_recovered": money_recovered,
        "total_disputes": total,
    }