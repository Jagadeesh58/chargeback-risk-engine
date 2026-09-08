"""Held-out system metrics for the canonical decision engine."""
from __future__ import annotations

import pandas as pd

from chargeback_risk_engine.engine.hybrid_pipeline import decide_case


def _row_to_dispute(row) -> dict:
    dispute = row.to_dict()
    for key, value in dispute.items():
        if isinstance(value, float) and pd.isna(value):
            dispute[key] = None
    return dispute


def run_pipeline(df: pd.DataFrame, *, db_path: str | None = None) -> pd.DataFrame:
    """Run every row through the same decision service used by the API/UI."""
    records = []
    for _, row in df.iterrows():
        dispute = _row_to_dispute(row)
        kwargs = {"include_counterfactual": False}
        if db_path is not None:
            kwargs["db_path"] = db_path
        result = decide_case(dispute, **kwargs)
        records.append({
            "dispute_id": dispute["dispute_id"],
            "reason_code": dispute["reason_code"],
            "amount": dispute["amount"],
            "would_win": dispute["would_win"],
            "p_win": result["win_probability"],
            "pass_count": sum(item["status"] == "PASS" for item in result["evidence"]),
            "evidence_total": len(result["evidence"]),
            "action": result["action"],
            "expected_value": result["expected_value"],
            "expected_recovery": result["economic_decision"]["expected_recovery"],
            "expected_net_value": result["economic_decision"]["expected_net_value"],
        })
    return pd.DataFrame(records)


def confusion_matrix_for_auto_contest(results: pd.DataFrame) -> dict:
    predicted_win = results["action"] == "AUTO-CONTEST"
    actual_win = results["would_win"] == True
    return {
        "true_positive": int((predicted_win & actual_win).sum()),
        "false_positive": int((predicted_win & ~actual_win).sum()),
        "true_negative": int((~predicted_win & ~actual_win).sum()),
        "false_negative": int((~predicted_win & actual_win).sum()),
    }


def precision_recall_f1(cm: dict) -> dict:
    tp, fp, fn = cm["true_positive"], cm["false_positive"], cm["false_negative"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def false_positive_cost(results: pd.DataFrame, contest_cost: float = 150.0) -> float:
    false_positives = results[(results["action"] == "AUTO-CONTEST") & (~results["would_win"])]
    return float(len(false_positives) * contest_cost)


def calibration_check(results: pd.DataFrame, n_bins: int = 5) -> pd.DataFrame:
    df = results.copy()
    df["bin"] = pd.cut(df["p_win"], bins=n_bins, include_lowest=True)
    return (
        df.groupby("bin", observed=True)
        .agg(avg_predicted=("p_win", "mean"), actual_win_rate=("would_win", "mean"), count=("p_win", "size"))
        .reset_index()
    )
