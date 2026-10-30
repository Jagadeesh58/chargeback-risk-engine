"""Test that artifact generation scripts produce reproducible output without drift."""
import json
from pathlib import Path
import pytest
from chargeback_risk_engine.paths import ARTIFACTS_DIR

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_hard_cases_report_reproducibility(tmp_path):
    import scripts.evaluate_hard_cases as hc
    hc.main(output_dir=tmp_path)

    generated = json.loads((tmp_path / "hard_cases_report.json").read_text(encoding="utf-8"))
    committed = json.loads((ARTIFACTS_DIR / "hard_cases_report.json").read_text(encoding="utf-8"))
    assert generated == committed


def test_oracle_ceiling_reproducibility(tmp_path):
    import scripts.oracle_ceiling as oc
    oc.main(output_dir=tmp_path)

    generated = json.loads((tmp_path / "oracle_ceiling.json").read_text(encoding="utf-8"))
    committed = json.loads((ARTIFACTS_DIR / "oracle_ceiling.json").read_text(encoding="utf-8"))
    assert generated == committed


def test_candidate_benchmark_reproducibility(tmp_path):
    import scripts.benchmark as bm
    bm.main(output_dir=tmp_path)

    generated = json.loads((tmp_path / "candidate_benchmark.json").read_text(encoding="utf-8"))
    committed = json.loads((ARTIFACTS_DIR / "candidate_benchmark.json").read_text(encoding="utf-8"))
    assert generated == committed


def test_strategy_comparison_reproducibility():
    import scripts.generate_report as gr
    oracle_data = json.loads((ARTIFACTS_DIR / "oracle_ceiling.json").read_text(encoding="utf-8"))
    bm_data = json.loads((ARTIFACTS_DIR / "candidate_benchmark.json").read_text(encoding="utf-8"))
    generated = gr.compute_strategy_comparison(bm_data["case_results"], oracle_data)
    committed = json.loads((ARTIFACTS_DIR / "strategy_comparison.json").read_text(encoding="utf-8"))
    assert generated == committed
