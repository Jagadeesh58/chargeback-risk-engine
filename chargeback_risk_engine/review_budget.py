"""Review-capacity optimization over deterministic case priority.

The priority is intentionally transparent: positive economic upside multiplied
by uncertainty, plus a small reward for cases with missing evidence. The final
selection remains a human-review queue; it never executes a financial action.
"""
from __future__ import annotations

import pandas as pd


def optimize_review_budget(results: pd.DataFrame, budgets: list[float] | None = None) -> pd.DataFrame:
    budgets = budgets or [0.01, 0.05, 0.10, 0.20]
    work = results.copy()
    total_evidence = work["evidence_total"].replace(0, 1)
    missingness = 1.0 - work["pass_count"] / total_evidence
    uncertainty = 1.0 - (work["p_win"] - 0.5).abs() * 2.0
    work["review_priority"] = (
        work["expected_net_value"].clip(lower=0.0) * uncertainty.clip(lower=0.0)
        + work["amount"] * 0.05 * missingness
    )
    uncertain = work[work["action"] == "HUMAN-REVIEW"].sort_values(
        ["review_priority", "amount"], ascending=[False, False]
    )
    total_wins = int(work["would_win"].sum())
    rows = []
    for budget in budgets:
        capacity = int(len(work) * float(budget))
        selected = uncertain.head(capacity)
        actual_positive = int(selected["would_win"].sum())
        recovered = float(selected.loc[selected["would_win"] == True, "amount"].sum())
        review_cost = float(len(selected) * 50.0)
        rows.append({
            "review_budget": float(budget),
            "capacity": capacity,
            "selected_reviews": len(selected),
            "precision_at_budget": actual_positive / len(selected) if len(selected) else 0.0,
            "recall_at_budget": actual_positive / total_wins if total_wins else 0.0,
            "recovered_value": recovered,
            "review_cost": review_cost,
            "incremental_net_value": recovered - review_cost,
            "false_positive_cost": float((~selected["would_win"]).sum() * 150.0),
        })
    return pd.DataFrame(rows)
