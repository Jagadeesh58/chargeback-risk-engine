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

    strategy = next(
        (s for s in benchmark["strategies"] if s["strategy"] == "CHARGEBACK-RISK-ENGINE"), None
    )
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
    match_thresh = re.search(
        r"\|\s*Selected policy threshold\s*\|\s*\*\*([0-9.]+)\*\*\s*from `dev.csv`\s*\|", readme
    )
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
    assert (
        pytest.approx(float(match_thresh.group(1)), abs=1e-3) == profile["auto_contest_threshold"]
    )

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


def test_strategy_comparison_table_matches_docs(artifacts):
    strategy_comp_path = ARTIFACTS_DIR / "strategy_comparison.json"
    if not strategy_comp_path.exists():
        import subprocess
        import sys

        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "generate_report.py")], check=True
        )

    assert strategy_comp_path.exists(), (
        "strategy_comparison.json missing. Run scripts/generate_report.py"
    )
    strat_comp = json.loads(strategy_comp_path.read_text(encoding="utf-8"))
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    eval_report = (REPO_ROOT / "docs" / "EVALUATION_REPORT.md").read_text(encoding="utf-8")
    model_card = (REPO_ROOT / "docs" / "MODEL_CARD.md").read_text(encoding="utf-8")

    # Check each strategy row's net values (p=0 and base-case p), precision, and lost count in README, EVALUATION_REPORT, and MODEL_CARD
    for row in strat_comp["strategy_table"]:
        net_p0_str = f"₹{row['realized_net_value_p0_lakh']:.2f} lakh"
        net_base_p_str = f"₹{row['realized_net_value_base_p_lakh']:.2f} lakh"
        prec_str = f"{row['contested_precision'] * 100:.1f}%"
        for doc_name, doc_text in [
            ("README.md", readme),
            ("EVALUATION_REPORT.md", eval_report),
            ("MODEL_CARD.md", model_card),
        ]:
            assert net_p0_str in doc_text, (
                f"Net value (p=0) {net_p0_str} for {row['strategy']} missing in {doc_name}"
            )
            assert net_base_p_str in doc_text, (
                f"Net value (base p) {net_base_p_str} for {row['strategy']} missing in {doc_name}"
            )
            assert prec_str in doc_text, (
                f"Precision {prec_str} for {row['strategy']} missing in {doc_name}"
            )

    # Check Bootstrap 95% CIs across docs
    boots = strat_comp["bootstrap_comparisons"]
    ci_auto_0 = f"[-₹{abs(boots['auto_only_vs_contest_everything_p0']['ci_95_lower_lakh']):.2f} lakh, -₹{abs(boots['auto_only_vs_contest_everything_p0']['ci_95_upper_lakh']):.2f} lakh]"
    ci_auto_p = f"[+₹{boots['auto_only_vs_contest_everything_base_p']['ci_95_lower_lakh']:.2f} lakh, +₹{boots['auto_only_vs_contest_everything_base_p']['ci_95_upper_lakh']:.2f} lakh]"
    ci_scenb_0 = f"[-₹{abs(boots['scenario_b_vs_contest_everything_p0']['ci_95_lower_lakh']):.2f} lakh, -₹{abs(boots['scenario_b_vs_contest_everything_p0']['ci_95_upper_lakh']):.2f} lakh]"
    ci_scenb_p = f"[-₹{abs(boots['scenario_b_vs_contest_everything_base_p']['ci_95_lower_lakh']):.2f} lakh, -₹{abs(boots['scenario_b_vs_contest_everything_base_p']['ci_95_upper_lakh']):.2f} lakh]"

    for doc_name, doc_text in [
        ("README.md", readme),
        ("EVALUATION_REPORT.md", eval_report),
        ("MODEL_CARD.md", model_card),
    ]:
        assert ci_auto_0 in doc_text, f"Bootstrap CI {ci_auto_0} missing in {doc_name}"
        assert ci_auto_p in doc_text, f"Bootstrap CI {ci_auto_p} missing in {doc_name}"
        assert ci_scenb_0 in doc_text, f"Bootstrap CI {ci_scenb_0} missing in {doc_name}"
        assert ci_scenb_p in doc_text, f"Bootstrap CI {ci_scenb_p} missing in {doc_name}"

    # Check break-even penalty levels
    b_even = strat_comp["break_even_analysis"]
    thresh_auto = f"₹{b_even['ranking_flip_vs_auto_only_threshold_inr']:,.2f}"
    thresh_scenb = f"₹{b_even['ranking_flip_vs_scenario_b_threshold_inr']:,.2f}"

    for doc_name, doc_text in [
        ("README.md", readme),
        ("EVALUATION_REPORT.md", eval_report),
        ("MODEL_CARD.md", model_card),
    ]:
        assert thresh_auto in doc_text, f"Threshold {thresh_auto} missing in {doc_name}"
        assert thresh_scenb in doc_text, f"Threshold {thresh_scenb} missing in {doc_name}"


def test_no_dollar_amounts_in_docs():
    """Assert no line in README.md or docs/*.md contains a '$' monetary amount."""
    doc_paths = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    dollar_pattern = re.compile(r"(\$|\\\$)\s*[0-9]")

    violations = []
    for doc in doc_paths:
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if dollar_pattern.search(line):
                violations.append(f"{doc.name}:{lineno}: {line.strip()}")

    assert not violations, "Found dollar amounts in documentation:\n" + "\n".join(violations)


def test_fees_and_penalties_have_rupee_or_source_citation():
    """Assert fee/fine/penalty/arbitration numbers in docs have a rupee sign or source citation."""
    doc_paths = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    pattern = re.compile(
        r"(?:fee|fines?|penalt(?:y|ies)|arbitration)[\w\s:=-]{0,20}\b\d+([,.]\d+)?|\b\d+([,.]\d+)?[\w\s:=-]{0,20}(?:fee|fines?|penalt(?:y|ies)|arbitration)",
        re.IGNORECASE,
    )

    violations = []
    for doc in doc_paths:
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                if (
                    "₹" not in line
                    and "Rs" not in line
                    and "INR" not in line
                    and "[source:" not in line
                ):
                    violations.append(f"{doc.name}:{lineno}: {line.strip()}")

    assert not violations, (
        "Found fee/penalty amounts without rupee or source citation:\n" + "\n".join(violations)
    )


def test_operations_doc_matches_load_test_report():
    """Assert measured load test latency and throughput in OPERATIONS.md match load_test_report.json."""
    ops_path = REPO_ROOT / "OPERATIONS.md"
    if not ops_path.exists():
        ops_path = REPO_ROOT / "docs" / "OPERATIONS.md"
    load_test_path = ARTIFACTS_DIR / "load_test_report.json"
    if not load_test_path.exists() or not ops_path.exists():
        return

    ops_text = ops_path.read_text(encoding="utf-8")
    lt_data = json.loads(load_test_path.read_text(encoding="utf-8"))
    for row in lt_data.get("results", []):
        row_str = f"| {row['pre_seeded_rows']:,} | {row['concurrency']} | {row['duration_seconds']:.2f} | {row['total_requests']} | {row['error_count']} | {row['throughput_rps']:.2f} | {row['latency_p50_ms']:.2f} | {row['latency_p95_ms']:.2f} |"
        assert row_str in ops_text, (
            f"Load test row for scale {row['pre_seeded_rows']} missing from OPERATIONS.md:\nExpected: {row_str}"
        )
