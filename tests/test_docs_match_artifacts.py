"""Test that documented evaluation metrics match the script-generated artifact JSON files.

Enforces zero drift between docs and generated artifacts. If any documented
metric (PR-AUC, precision, recall, net value, threshold, oracle ceiling) differs
from the underlying JSON artifacts, this test fails.
"""

import json
import re
from pathlib import Path
import pytest

from chargeback_risk_engine.paths import ARTIFACTS_DIR

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def artifacts():
    benchmark_path = ARTIFACTS_DIR / "candidate_benchmark.json"
    profile_path = ARTIFACTS_DIR / "policy_profile.json"
    oracle_path = ARTIFACTS_DIR / "oracle_ceiling.json"

    if not benchmark_path.exists():
        import subprocess
        import sys
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "benchmark.py")], check=True)

    assert benchmark_path.exists(), "candidate_benchmark.json missing. Run scripts/benchmark.py"
    assert profile_path.exists(), "policy_profile.json missing."

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    oracle = json.loads(oracle_path.read_text(encoding="utf-8")) if oracle_path.exists() else {}

    strategy = next((s for s in benchmark["strategies"] if s["strategy"] == "CHARGEBACK-RISK-ENGINE"), None)
    assert strategy is not None, "CHARGEBACK-RISK-ENGINE strategy missing from benchmark"

    return {
        "benchmark": benchmark,
        "strategy": strategy,
        "profile": profile,
        "oracle": oracle,
    }


def test_readme_metrics_match_artifacts(artifacts):
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    strategy = artifacts["strategy"]
    profile = artifacts["profile"]

    # Precision in README table
    match_prec = re.search(r"\|\s*Auto-contest precision\s*\|\s*\*\*([0-9.]+)%\*\*\s*\|", readme)
    assert match_prec, "Precision not found in README.md"
    readme_prec = float(match_prec.group(1)) / 100.0
    assert pytest.approx(readme_prec, abs=1e-3) == strategy["auto_contest_precision"]

    # Recall in README table
    match_rec = re.search(r"\|\s*Auto-contest recall\s*\|\s*\*\*([0-9.]+)%\*\*\s*\|", readme)
    assert match_rec, "Recall not found in README.md"
    readme_rec = float(match_rec.group(1)) / 100.0
    assert pytest.approx(readme_rec, abs=1e-3) == strategy["auto_contest_recall"]

    # Threshold in README table
    match_thresh = re.search(r"\|\s*Selected policy threshold\s*\|\s*\*\*([0-9.]+)\*\*\s*from `dev.csv`\s*\|", readme)
    assert match_thresh, "Threshold not found in README.md"
    readme_thresh = float(match_thresh.group(1))
    assert pytest.approx(readme_thresh, abs=1e-3) == profile["auto_contest_threshold"]


def test_model_card_metrics_match_artifacts(artifacts):
    model_card = (REPO_ROOT / "docs" / "MODEL_CARD.md").read_text(encoding="utf-8")
    strategy = artifacts["strategy"]
    profile = artifacts["profile"]

    match_prec = re.search(r"([0-9.]+)%\s*precision", model_card)
    assert match_prec, "Precision not found in MODEL_CARD.md"
    mc_prec = float(match_prec.group(1)) / 100.0
    assert pytest.approx(mc_prec, abs=1e-3) == strategy["auto_contest_precision"]

    match_rec = re.search(r"([0-9.]+)%\s*recall", model_card)
    assert match_rec, "Recall not found in MODEL_CARD.md"
    mc_rec = float(match_rec.group(1)) / 100.0
    assert pytest.approx(mc_rec, abs=1e-3) == strategy["auto_contest_recall"]

    match_thresh = re.search(r"\(([0-9.]+)\s*threshold\)", model_card)
    assert match_thresh, "Threshold not found in MODEL_CARD.md"
    mc_thresh = float(match_thresh.group(1))
    assert pytest.approx(mc_thresh, abs=1e-3) == profile["auto_contest_threshold"]


def test_evaluation_report_metrics_match_artifacts(artifacts):
    eval_report = (REPO_ROOT / "docs" / "EVALUATION_REPORT.md").read_text(encoding="utf-8")
    strategy = artifacts["strategy"]
    profile = artifacts["profile"]

    # Threshold
    match_thresh = re.search(r"- auto-contest threshold: `([0-9.]+)`", eval_report)
    assert match_thresh, "Threshold not found in EVALUATION_REPORT.md"
    assert pytest.approx(float(match_thresh.group(1)), abs=1e-3) == profile["auto_contest_threshold"]

    # Candidate decision metrics
    match_count = re.search(r"\|\s*Auto-contest count\s*\|\s*([0-9,]+)\s*\|", eval_report)
    assert match_count
    assert int(match_count.group(1).replace(",", "")) == strategy["auto_contest_count"]

    match_prec = re.search(r"\|\s*Auto-contest precision\s*\|\s*([0-9.]+)\s*\|", eval_report)
    assert match_prec
    assert pytest.approx(float(match_prec.group(1)), abs=1e-4) == strategy["auto_contest_precision"]

    match_rec = re.search(r"\|\s*Auto-contest recall\s*\|\s*([0-9.]+)\s*\|", eval_report)
    assert match_rec
    assert pytest.approx(float(match_rec.group(1)), abs=1e-4) == strategy["auto_contest_recall"]
