"""Regression tests for bring-your-own-data evaluation harness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
import pandas as pd

from scripts.evaluate_real_data import evaluate_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = REPO_ROOT / "data" / "sample_external_disputes.csv"


def test_evaluate_real_data_with_ground_truth():
    report = evaluate_dataset(SAMPLE_CSV, loss_penalty_inr=4150.0)
    assert report["total_disputes"] == 10
    assert report["total_disputed_amount_inr"] > 0
    assert report["has_ground_truth_labels"] is True

    op = report["operational_distribution"]
    assert "AUTO-CONTEST" in op
    assert "HUMAN-REVIEW" in op
    assert "ACCEPT-LOSS" in op
    assert op["AUTO-CONTEST"]["count"] + op["HUMAN-REVIEW"]["count"] + op["ACCEPT-LOSS"]["count"] == 10

    gt = report["ground_truth_evaluation"]
    assert "auto_contest_precision" in gt
    assert "auto_contest_recall" in gt
    assert "realized_net_value_p0_inr" in gt
    assert "realized_net_value_base_p_inr" in gt


def test_evaluate_real_data_without_ground_truth(tmp_path: Path):
    """External CSV with no labels should output operational routing without crashing."""
    df = pd.read_csv(SAMPLE_CSV)
    df_no_labels = df.drop(columns=["would_win"])
    unlabeled_csv = tmp_path / "unlabeled_disputes.csv"
    df_no_labels.to_csv(unlabeled_csv, index=False)

    report = evaluate_dataset(unlabeled_csv)
    assert report["total_disputes"] == 10
    assert report["has_ground_truth_labels"] is False
    assert "notice" in report["ground_truth_evaluation"]
    assert "without merchant contest outcomes" in report["ground_truth_evaluation"]["notice"]


def test_evaluate_real_data_missing_columns_fails(tmp_path: Path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("dispute_id,amount\nD1,100.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing mandatory columns"):
        evaluate_dataset(bad_csv)


def test_evaluate_real_data_cli(tmp_path: Path):
    out_json = tmp_path / "cli_report.json"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "evaluate_real_data.py"),
        "--csv",
        str(SAMPLE_CSV),
        "--out",
        str(out_json),
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        env={**dict(os.environ), "PYTHONIOENCODING": "utf-8"},
    )
    assert "DATASET EVALUATION REPORT" in res.stdout
    assert out_json.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["total_disputes"] == 10
