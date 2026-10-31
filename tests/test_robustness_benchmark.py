"""Test that robustness benchmark runs within budget and produces stable schema."""
import time
from pathlib import Path
import pytest

from scripts.robustness_benchmark import run_robustness_benchmark, OUTPUT_PATH


def test_robustness_benchmark_runs_under_60s_with_stable_schema(tmp_path):
    out_file = tmp_path / "robustness_report.json"
    start_time = time.time()
    report = run_robustness_benchmark(output_path=out_file, n_per_scenario=100)
    elapsed = time.time() - start_time

    assert elapsed < 60.0, f"Benchmark took {elapsed:.2f}s, exceeding 60s limit"
    assert out_file.exists()

    assert report["benchmark"] == "robustness_perturbation_sweep"
    assert "circular by construction" in report["methodology_disclaimer"].lower()
    assert report["synthetic"] is True

    expected_scenarios = [
        "baseline",
        "missingness_low_5pct",
        "missingness_high_35pct",
        "contradiction_low_2pct",
        "contradiction_high_20pct",
        "field_rate_low_65pct",
        "field_rate_high_90pct",
        "base_rate_low_45pct",
        "base_rate_high_75pct",
        "label_noise_5pct",
        "label_noise_10pct",
        "label_noise_20pct",
        "covariate_shift_amount",
        "covariate_shift_reasons",
    ]

    for sc in expected_scenarios:
        assert sc in report["scenarios"], f"Scenario {sc} missing from report"
        metrics = report["scenarios"][sc]
        assert "precision" in metrics
        assert "recall" in metrics
        assert "auto_contest_rate" in metrics
        assert "auto_contest_count" in metrics
        assert "human_review_count" in metrics
        assert "accept_loss_count" in metrics
        assert "expected_net_value" in metrics
        assert 0.0 <= metrics["precision"] <= 1.0
        assert 0.0 <= metrics["recall"] <= 1.0
        assert 0.0 <= metrics["auto_contest_rate"] <= 1.0
        assert metrics["cases"] == 100


def test_committed_robustness_report_exists_and_matches_schema():
    assert OUTPUT_PATH.exists(), "artifacts/robustness_report.json missing. Run scripts/robustness_benchmark.py"
    import json
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "circular by construction" in data["methodology_disclaimer"].lower()
    assert "baseline" in data["scenarios"]
    assert "label_noise_20pct" in data["scenarios"]
