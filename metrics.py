"""
metrics.py — evaluates the full scorer -> evidence -> policy pipeline
against a held-out set. Computes the confusion matrix, precision,
recall, F1, false-positive cost, and a calibration check.

IMPORTANT: this is meant to be run against test.csv exactly once for
final reporting -- not used repeatedly to tune the scorer or policy
(that's what dev.csv is for). Touching test.csv repeatedly would make
"held-out" a false claim.
"""

import pandas as pd

from scorer import predict_win_probability
from policy import decide
from evidence import assemble


def _row_to_dispute(row) -> dict:
    """Convert a pandas row into a plain dict with proper None handling
    (pandas reads missing CSV values as NaN, not None)."""
    dispute = row.to_dict()
    for k, v in dispute.items():
        if isinstance(v, float) and pd.isna(v):
            dispute[k] = None
    return dispute


def run_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    """Runs every dispute through scorer -> evidence -> policy, returns
    a results dataframe with predictions alongside the true label."""
    records = []
    for _, row in df.iterrows():
        dispute = _row_to_dispute(row)
        p_win = predict_win_probability(dispute)
        packet = assemble(dispute)
        decision = decide(win_probability=p_win, amount=dispute["amount"], evidence_packet=packet)

        records.append({
            "dispute_id": dispute["dispute_id"],
            "reason_code": dispute["reason_code"],
            "amount": dispute["amount"],
            "would_win": dispute["would_win"],
            "p_win": p_win,
            "pass_count": packet.pass_count,
            "evidence_total": packet.total,
            "action": decision.action,
            "expected_value": decision.expected_value,
        })
    return pd.DataFrame(records)


def confusion_matrix_for_auto_contest(results: pd.DataFrame) -> dict:
    """
    Treats AUTO-CONTEST as a positive prediction ("we predict this wins")
    and everything else (HUMAN REVIEW, ACCEPT LOSS) as a negative
    prediction for this specific matrix. HUMAN REVIEW cases are counted
    as "we did not commit to a win prediction" -- a deliberate choice,
    since they're not autonomous decisions.
    """
    predicted_win = results["action"] == "AUTO-CONTEST"
    actual_win = results["would_win"] == True

    true_positive = ((predicted_win) & (actual_win)).sum()
    false_positive = ((predicted_win) & (~actual_win)).sum()
    true_negative = ((~predicted_win) & (~actual_win)).sum()
    false_negative = ((~predicted_win) & (actual_win)).sum()

    return {
        "true_positive": int(true_positive),
        "false_positive": int(false_positive),
        "true_negative": int(true_negative),
        "false_negative": int(false_negative),
    }


def precision_recall_f1(cm: dict) -> dict:
    tp, fp, fn = cm["true_positive"], cm["false_positive"], cm["false_negative"]
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def false_positive_cost(results: pd.DataFrame, contest_cost: float = 150.0) -> float:
    """
    Total cost of AUTO-CONTEST decisions that turned out to lose: just
    the contest fee. Matches policy.py's own EV assumption
    (RISK_COST_IF_LOSE_CONTEST = 0.0) -- the disputed amount was already
    reversed from the merchant by the chargeback itself, contest or not,
    so losing a contest doesn't cost the amount AGAIN on top of the fee.
    Contesting and losing is only ever worse than not contesting by the
    wasted fee, not by the full amount.
    """
    false_positives = results[(results["action"] == "AUTO-CONTEST") & (~results["would_win"])]
    return float(len(false_positives) * contest_cost)


def calibration_check(results: pd.DataFrame, n_bins: int = 5) -> pd.DataFrame:
    """
    Buckets disputes by predicted p_win into bins, and for each bin
    reports the average predicted probability vs the actual observed
    win rate. A well-calibrated scorer has these two columns close
    to each other in every bin.
    """
    df = results.copy()
    df["bin"] = pd.cut(df["p_win"], bins=n_bins, include_lowest=True)
    grouped = df.groupby("bin", observed=True).agg(
        avg_predicted=("p_win", "mean"),
        actual_win_rate=("would_win", "mean"),
        count=("p_win", "size"),
    ).reset_index()
    return grouped