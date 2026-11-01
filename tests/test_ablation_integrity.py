import pandas as pd

from scripts.generate_report import _ablation


def test_ablation_modes_are_not_a_copy_of_one_another():
    df = pd.read_csv("data/dev.csv").head(250)
    rows = _ablation(df)
    signatures = {
        (r["component"], r["auto_contest_count"], round(r["precision"], 6), round(r["recall"], 6))
        for r in rows
    }
    assert len(signatures) >= 3
    # The full report must not silently present identical pipelines as separate ablations.
    assert (
        len(
            {
                (r["auto_contest_count"], round(r["precision"], 6), round(r["recall"], 6))
                for r in rows
            }
        )
        >= 3
    )


def test_ablation_artifacts_exist_and_consistent():
    """Verify that ablation artifacts exist and have expected structure."""
    import json
    from pathlib import Path

    artifacts_dir = Path("artifacts")
    for name in (
        "ablations.json",
        "calibration_assessment.json",
        "evaluation_confidence_intervals.json",
    ):
        path = artifacts_dir / name
        assert path.exists(), f"Missing ablation artifact: {name}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"Artifact {name} must be a JSON object"


def test_verify_no_leakage_script_passes():
    """Verify scripts/verify_no_leakage.py exits with code 0."""
    import subprocess
    import sys

    res = subprocess.run(
        [sys.executable, "scripts/verify_no_leakage.py"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"verify_no_leakage.py failed: {res.stderr}"
    assert "Reason-code-AWARE (per-reason submodel) AUC" in res.stdout
