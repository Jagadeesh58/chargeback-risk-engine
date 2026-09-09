"""Review-capacity optimization over deterministic case priority."""
from __future__ import annotations

import pandas as pd


def optimize_review_budget(results: pd.DataFrame, budgets: list[float] | None = None) -> pd.DataFrame:
    budgets = budgets or [0.01, 0.05, 0.10, 0.20]
    work = results.copy()
    work["review_priority"] = (
        work["expected_net_value"].clip(lower=0.0)
        * (1.0 - work["p_win"].sub(0.5).abs())
        + work["amount"] * 0.10 * work["evidence_total"].rsub(work["pass_count"]).clip(lower=0)
    )
    uncertain = work[work["action"] == "HUMAN-REVIEW"].sort_values("review_priority", ascending=False)
    rows = []
    for budget in budgets:
        capacity = int(len(work) * budget)
        selected = uncertain.head(capacity)
        actual_positive = int(selected["would_win"].sum())
        recovered = float(selected.loc[selected["would_win"] == True, "amount"].sum())
        false_positive_cost = float((~selected["would_win"]).sum() * 150.0)
        rows.append({
            "review_budget": budget,
            "capacity": capacity,
            "selected_reviews": len(selected),
            "precision_at_budget": actual_positive / len(selected) if len(selected) else 0.0,
            "recall_at_budget": actual_positive / int(work["would_win"].sum()) if int(work["would_win"].sum()) else 0.0,
            "recovered_value": recovered,
            "false_positive_cost": false_positive_cost,
        })
    return pd.DataFrame(rows)
