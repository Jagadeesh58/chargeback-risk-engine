"""
sensitivity.py — measures how precision, recall, and false-positive
cost change as we sweep AUTO_CONTEST_THRESHOLD and MONETARY_CEILING
across a range of values, instead of trusting the single hand-picked
values in policy.py by assumption alone.
"""

import pandas as pd

from chargeback_risk_engine.scorer import predict_win_probability
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.metrics import _row_to_dispute


def _decide_with_custom_threshold(win_probability, amount, evidence_packet,
                                    auto_contest_threshold, monetary_ceiling,
                                    min_pass_fraction=0.5):
    """
    A standalone copy of policy.decide()'s logic, parameterized so we can
    sweep thresholds without needing to mutate the real policy.py's
    module-level constants (which would be fragile and non-reentrant).
    """
    if amount > monetary_ceiling:
        return "HUMAN REVIEW"

    if win_probability >= auto_contest_threshold:
        if evidence_packet.total > 0:
            pass_fraction = evidence_packet.pass_count / evidence_packet.total
            if pass_fraction < min_pass_fraction:
                return "HUMAN REVIEW"
        return "AUTO-CONTEST"
    elif win_probability <= 0.30:  # ACCEPT_LOSS_THRESHOLD, kept fixed for this sweep
        return "ACCEPT LOSS"
    else:
        return "HUMAN REVIEW"


def sweep_auto_contest_threshold(df: pd.DataFrame, thresholds: list[float],
                                   contest_cost: float = 150.0) -> pd.DataFrame:
    """
    Precomputes P(win) and evidence packets ONCE (expensive), then sweeps
    the threshold cheaply -- avoids recomputing the scorer for every
    threshold value.
    """
    precomputed = []
    for _, row in df.iterrows():
        dispute = _row_to_dispute(row)
        p_win = predict_win_probability(dispute)
        packet = assemble(dispute)
        precomputed.append({
            "amount": dispute["amount"],
            "would_win": dispute["would_win"],
            "p_win": p_win,
            "packet": packet,
        })

    results = []
    for threshold in thresholds:
        tp = fp = tn = fn = 0
        fp_cost = 0.0
        for row in precomputed:
            action = _decide_with_custom_threshold(
                row["p_win"], row["amount"], row["packet"],
                auto_contest_threshold=threshold,
                monetary_ceiling=50_000.0,
            )
            predicted_win = action == "AUTO-CONTEST"
            actual_win = row["would_win"] == True

            if predicted_win and actual_win:
                tp += 1
            elif predicted_win and not actual_win:
                fp += 1
                fp_cost += contest_cost  # matches policy.py's EV assumption: losing
                # costs just the fee, not the fee plus the amount (see metrics.py)
            elif not predicted_win and not actual_win:
                tn += 1
            else:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        results.append({
            "threshold": threshold,
            "precision": precision,
            "recall": recall,
            "auto_contest_count": tp + fp,
            "false_positive_cost": fp_cost,
        })

    return pd.DataFrame(results)


def sweep_monetary_ceiling(df: pd.DataFrame, ceilings: list[float],
                             contest_cost: float = 150.0) -> pd.DataFrame:
    """Same idea, sweeping MONETARY_CEILING instead, threshold fixed at 0.65."""
    precomputed = []
    for _, row in df.iterrows():
        dispute = _row_to_dispute(row)
        p_win = predict_win_probability(dispute)
        packet = assemble(dispute)
        precomputed.append({
            "amount": dispute["amount"],
            "would_win": dispute["would_win"],
            "p_win": p_win,
            "packet": packet,
        })

    results = []
    for ceiling in ceilings:
        tp = fp = 0
        fp_cost = 0.0
        human_review_count = 0
        for row in precomputed:
            action = _decide_with_custom_threshold(
                row["p_win"], row["amount"], row["packet"],
                auto_contest_threshold=0.65,
                monetary_ceiling=ceiling,
            )
            if action == "HUMAN REVIEW":
                human_review_count += 1
            predicted_win = action == "AUTO-CONTEST"
            actual_win = row["would_win"] == True
            if predicted_win and actual_win:
                tp += 1
            elif predicted_win and not actual_win:
                fp += 1
                fp_cost += contest_cost  # matches policy.py's EV assumption: losing
                # costs just the fee, not the fee plus the amount (see metrics.py)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        results.append({
            "ceiling": ceiling,
            "precision": precision,
            "auto_contest_count": tp + fp,
            "human_review_count": human_review_count,
            "false_positive_cost": fp_cost,
        })

    return pd.DataFrame(results)