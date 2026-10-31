"""scripts/evaluate_real_data.py — Bring-Your-Own-Data evaluation harness for external merchant datasets."""

from __future__ import annotations

import argparse
import json
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import tempfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("CHARGEBACK_ENV", "development")

import pandas as pd

from chargeback_risk_engine.config import REASON_CODES
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.risk_graph import RiskGraph
from chargeback_risk_engine.policy import CONTEST_COST

HUMAN_REVIEW_COST = 50.0


def evaluate_dataset(
    csv_path: str | Path,
    loss_penalty_inr: float = 4150.0,
) -> dict[str, Any]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Input dataset not found: {path}")

    df = pd.read_csv(path)

    # Validate minimal columns
    required_cols = {"dispute_id", "reason_code", "amount"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing mandatory columns: {missing}. Required: {sorted(required_cols)}")

    # Ground-truth outcome detection
    has_ground_truth = False
    outcome_col = ""
    for cand in ("would_win", "won", "is_won", "outcome"):
        if cand in df.columns:
            has_ground_truth = True
            outcome_col = cand
            break

    n_disputes = len(df)
    total_amount = float(df["amount"].sum())

    # Temporary database and graph for execution
    with tempfile.TemporaryDirectory(prefix="evaluate_real_data_") as tmp_dir:
        db_path = str(Path(tmp_dir) / "temp_audit.db")
        graph = RiskGraph()

        results = []
        for _, row in df.iterrows():
            d = row.to_dict()
            for k, v in list(d.items()):
                if isinstance(v, float) and pd.isna(v):
                    d[k] = None
            res = decide_case(
                d,
                risk_graph=graph,
                db_path=db_path,
                include_counterfactual=False,
                call_ai_analyst=False,
            )
            results.append(res)

    actions = [r["action"] for r in results]
    auto_indices = [i for i, a in enumerate(actions) if a == "AUTO-CONTEST"]
    review_indices = [i for i, a in enumerate(actions) if a == "HUMAN-REVIEW"]
    accept_indices = [i for i, a in enumerate(actions) if a == "ACCEPT-LOSS"]

    auto_count = len(auto_indices)
    review_count = len(review_indices)
    accept_count = len(accept_indices)

    auto_amount = float(df.iloc[auto_indices]["amount"].sum()) if auto_indices else 0.0
    review_amount = float(df.iloc[review_indices]["amount"].sum()) if review_indices else 0.0
    accept_amount = float(df.iloc[accept_indices]["amount"].sum()) if accept_indices else 0.0

    expected_recoveries = [r["win_probability"] * float(r["amount"]) for r in results]
    auto_expected_recovery = sum(expected_recoveries[i] for i in auto_indices)

    summary: dict[str, Any] = {
        "dataset_path": str(path),
        "total_disputes": n_disputes,
        "total_disputed_amount_inr": round(total_amount, 2),
        "total_disputed_amount_lakh": round(total_amount / 100000.0, 2),
        "has_ground_truth_labels": has_ground_truth,
        "operational_distribution": {
            "AUTO-CONTEST": {
                "count": auto_count,
                "share": round(auto_count / n_disputes, 4) if n_disputes else 0.0,
                "amount_inr": round(auto_amount, 2),
                "expected_recovery_inr": round(auto_expected_recovery, 2),
            },
            "HUMAN-REVIEW": {
                "count": review_count,
                "share": round(review_count / n_disputes, 4) if n_disputes else 0.0,
                "amount_inr": round(review_amount, 2),
            },
            "ACCEPT-LOSS": {
                "count": accept_count,
                "share": round(accept_count / n_disputes, 4) if n_disputes else 0.0,
                "amount_inr": round(accept_amount, 2),
            },
        },
    }

    if has_ground_truth:
        y_true = df[outcome_col].astype(bool).to_numpy()
        auto_wins = int(sum(y_true[i] for i in auto_indices))
        auto_losses = auto_count - auto_wins
        total_wins = int(sum(y_true))

        precision = (auto_wins / auto_count) if auto_count > 0 else 0.0
        recall = (auto_wins / total_wins) if total_wins > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        realized_recovery = float(df.iloc[[i for i in auto_indices if y_true[i]]]["amount"].sum())
        contest_fees = auto_count * CONTEST_COST
        review_fees = review_count * HUMAN_REVIEW_COST

        net_val_p0 = realized_recovery - contest_fees - review_fees
        net_val_base_p = net_val_p0 - (auto_losses * loss_penalty_inr)

        summary["ground_truth_evaluation"] = {
            "outcome_column": outcome_col,
            "overall_win_rate": round(total_wins / n_disputes, 4) if n_disputes else 0.0,
            "auto_contest_precision": round(precision, 4),
            "auto_contest_recall": round(recall, 4),
            "auto_contest_f1": round(f1, 4),
            "won_auto_contests": auto_wins,
            "lost_auto_contests": auto_losses,
            "realized_gross_recovery_inr": round(realized_recovery, 2),
            "realized_net_value_p0_inr": round(net_val_p0, 2),
            "realized_net_value_p0_lakh": round(net_val_p0 / 100000.0, 2),
            "realized_net_value_base_p_inr": round(net_val_base_p, 2),
            "realized_net_value_base_p_lakh": round(net_val_base_p / 100000.0, 2),
            "assumed_loss_penalty_inr": loss_penalty_inr,
        }
    else:
        summary["ground_truth_evaluation"] = {
            "notice": (
                "Dataset does not contain a ground-truth resolution column ('would_win'/'won'). "
                "Realized precision, recall, and win counts cannot be evaluated without merchant contest outcomes. "
                "Operational routing and expected values are reported above."
            )
        }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate external chargeback dataset with Chargeback Risk Engine")
    parser.add_argument("--csv", type=str, required=True, help="Path to CSV dispute file")
    parser.add_argument("--out", type=str, default="", help="Optional JSON output destination")
    parser.add_argument("--penalty", type=float, default=4150.0, help="Assumed penalty per lost contest (INR)")
    args = parser.parse_args()

    results = evaluate_dataset(args.csv, loss_penalty_inr=args.penalty)

    print("\n================ DATASET EVALUATION REPORT ================")
    print(f"Dataset:            {results['dataset_path']}")
    print(f"Total Disputes:     {results['total_disputes']}")
    print(f"Total Volume:       ₹{results['total_disputed_amount_inr']:,.2f} ({results['total_disputed_amount_lakh']} lakh)")
    print("\nOperational Routing:")
    for action, stats in results["operational_distribution"].items():
        print(f"  {action:<15}: {stats['count']:>4} ({stats['share']*100:>5.1f}%) | ₹{stats['amount_inr']:>12,.2f}")

    gt = results["ground_truth_evaluation"]
    if "notice" in gt:
        print(f"\nGround Truth:       Not Provided ({gt['notice']})")
    else:
        print("\nGround Truth Performance:")
        print(f"  Auto Precision:   {gt['auto_contest_precision']*100:.1f}%")
        print(f"  Auto Recall:      {gt['auto_contest_recall']*100:.1f}%")
        print(f"  Net Value (p=0):  ₹{gt['realized_net_value_p0_inr']:,.2f} ({gt['realized_net_value_p0_lakh']} lakh)")
        print(f"  Net Value (base): ₹{gt['realized_net_value_base_p_inr']:,.2f} ({gt['realized_net_value_base_p_lakh']} lakh)")
    print("===========================================================\n")

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Saved evaluation report to {out_p}")


if __name__ == "__main__":
    main()
