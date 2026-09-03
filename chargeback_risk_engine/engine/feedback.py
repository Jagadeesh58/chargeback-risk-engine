"""Outcome feedback storage and analytics helpers."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class OutcomeFeedback:
    dispute_id: str
    predicted_probability: float
    action: str
    contest_outcome: str | None
    final_chargeback_outcome: str | None
    recovered_amount: float | None
    model_version: str
    feature_version: str
    recorded_at: str


def ensure_feedback_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS outcomes (
                dispute_id TEXT PRIMARY KEY,
                predicted_probability REAL NOT NULL,
                action TEXT NOT NULL,
                contest_outcome TEXT,
                final_chargeback_outcome TEXT,
                recovered_amount REAL,
                model_version TEXT NOT NULL,
                feature_version TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )"""
        )


def record_outcome(
    db_path: str,
    dispute_id: str,
    predicted_probability: float,
    action: str,
    contest_outcome: str | None = None,
    final_chargeback_outcome: str | None = None,
    recovered_amount: float | None = None,
    model_version: str = "rules-v1",
    feature_version: str = "features-v1",
) -> OutcomeFeedback:
    ensure_feedback_table(db_path)
    feedback = OutcomeFeedback(
        dispute_id=dispute_id,
        predicted_probability=float(predicted_probability),
        action=action,
        contest_outcome=contest_outcome,
        final_chargeback_outcome=final_chargeback_outcome,
        recovered_amount=recovered_amount,
        model_version=model_version,
        feature_version=feature_version,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (*asdict(feedback).values(), json.dumps(asdict(feedback))),
        )
    return feedback


def feedback_metrics(db_path: str) -> dict:
    """Compute outcome analytics from confirmed feedback rows only.

    Rows without a final outcome remain available for future labeling but do not
    contaminate accuracy metrics.
    """
    ensure_feedback_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT predicted_probability, action, final_chargeback_outcome, recovered_amount FROM outcomes").fetchall()
    labeled = [r for r in rows if r[2] is not None]
    if not labeled:
        return {"total_records": len(rows), "labeled_records": 0}
    correct = 0
    reviewed = 0
    recovered = 0.0
    for probability, action, outcome, recovered_amount in labeled:
        actual_win = str(outcome).upper() in {"WON", "RECOVERED", "SUCCESS", "TRUE", "1"}
        predicted_win = float(probability) >= 0.5
        correct += int(predicted_win == actual_win)
        reviewed += int(action == "HUMAN REVIEW")
        recovered += float(recovered_amount or 0.0)
    return {
        "total_records": len(rows),
        "labeled_records": len(labeled),
        "prediction_accuracy": correct / len(labeled),
        "human_review_rate": reviewed / len(labeled),
        "recovered_value": recovered,
    }


def build_retraining_dataset(db_path: str, output_csv: str = "artifacts/retraining_feedback.csv") -> int:
    """Export only confirmed-outcome feedback for future model validation.
    This never retrains a model automatically.
    """
    import csv
    ensure_feedback_table(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT dispute_id, predicted_probability, action, final_chargeback_outcome, recovered_amount, model_version, feature_version, recorded_at FROM outcomes WHERE final_chargeback_outcome IS NOT NULL").fetchall()
    Path = __import__("pathlib").Path
    path = Path(output_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["dispute_id", "predicted_probability", "action", "final_chargeback_outcome", "recovered_amount", "model_version", "feature_version", "recorded_at"])
        writer.writerows(rows)
    return len(rows)
