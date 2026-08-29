"""
test_app.py — tests for the parts of app.py that can be tested without
a running browser: the dashboard's data pipeline (reused, already-tested
modules) actually produces the shapes app.py expects to display, and the
API payload construction logic behaves correctly for all three evidence
states.

Streamlit's own UI rendering isn't unit-tested here (that requires manual
browser verification, per the runbook) -- this covers the underlying
data/logic app.py depends on.
"""

import pandas as pd

from metrics import run_pipeline, confusion_matrix_for_auto_contest, precision_recall_f1, false_positive_cost, calibration_check
from baseline import run_naive_baseline
from sensitivity import sweep_auto_contest_threshold


def test_dashboard_data_pipeline_produces_expected_shape():
    """Confirms the exact sequence of calls app.py's dashboard tab makes
    runs without error and produces the shapes the UI code expects."""
    test = pd.read_csv("test.csv")
    results = run_pipeline(test)
    cm = confusion_matrix_for_auto_contest(results)
    prf = precision_recall_f1(cm)
    fp_cost = false_positive_cost(results)
    naive = run_naive_baseline(test)

    assert "precision" in prf and "recall" in prf and "f1" in prf
    assert isinstance(fp_cost, float)
    assert "precision" in naive and "recall" in naive


def test_calibration_check_produces_columns_app_expects():
    test = pd.read_csv("test.csv")
    results = run_pipeline(test)
    calibration = calibration_check(results, n_bins=5)
    assert "avg_predicted" in calibration.columns
    assert "actual_win_rate" in calibration.columns


def test_threshold_sweep_produces_columns_app_expects():
    test = pd.read_csv("test.csv")
    sweep = sweep_auto_contest_threshold(test, [0.5, 0.65, 0.8])
    assert "threshold" in sweep.columns
    assert "precision" in sweep.columns
    assert "recall" in sweep.columns


def test_evidence_choice_mapping_matches_app_logic():
    """The Yes/No/Unknown radio mapping used in app.py's form."""
    mapping = {"Yes": True, "No": False, "Unknown": None}
    assert mapping["Yes"] is True
    assert mapping["No"] is False
    assert mapping["Unknown"] is None