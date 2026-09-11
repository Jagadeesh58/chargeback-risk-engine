"""
tests/test_app.py

Tests for the parts of apps/app_deployed.py that can be verified
without launching a browser.

The Streamlit rendering itself is not unit-tested here. Instead,
this file validates the data/logic pipeline that the dashboard
depends on, plus the structure of the deterministic demo cases.
"""

import ast

import pandas as pd

from chargeback_risk_engine.metrics import (
    calibration_check,
    confusion_matrix_for_auto_contest,
    false_positive_cost,
    precision_recall_f1,
    run_pipeline,
)

from chargeback_risk_engine.baseline import run_naive_baseline

from chargeback_risk_engine.sensitivity import (
    sweep_auto_contest_threshold,
)

from chargeback_risk_engine.calibration import (
    calibration_error,
    fit_calibration_points,
)


def test_dashboard_data_pipeline_produces_expected_shape():
    """
    Confirms the dashboard's core data pipeline runs successfully
    and produces the fields expected by the UI.
    """
    test = pd.read_csv("data/test.csv").head(100)

    results = run_pipeline(test)

    cm = confusion_matrix_for_auto_contest(results)
    prf = precision_recall_f1(cm)

    fp_cost = false_positive_cost(results)
    naive = run_naive_baseline(test)

    assert "precision" in prf
    assert "recall" in prf
    assert "f1" in prf

    assert isinstance(fp_cost, float)

    assert "precision" in naive
    assert "recall" in naive


def test_calibration_check_produces_columns_app_expects():
    """
    Confirms calibration_check() returns the columns used by
    the dashboard calibration display.
    """
    test = pd.read_csv("data/test.csv").head(100)

    results = run_pipeline(test)

    calibration = calibration_check(
        results,
        n_bins=5,
    )

    assert "avg_predicted" in calibration.columns
    assert "actual_win_rate" in calibration.columns


def test_calibration_error_comparison_matches_app_logic():
    """
    Confirms the raw-vs-calibrated comparison used by the
    dashboard runs successfully and returns valid errors.
    """
    test = pd.read_csv("data/test.csv").head(100)

    results = run_pipeline(test)

    calib_points = fit_calibration_points(
        "data/dev.csv"
    )

    pairs = list(
        zip(
            results["p_win"],
            results["would_win"].astype(float),
        )
    )

    raw_error = calibration_error(
        pairs,
        points=None,
    )

    calibrated_error = calibration_error(
        pairs,
        points=calib_points,
    )

    assert 0.0 <= raw_error <= 1.0
    assert 0.0 <= calibrated_error <= 1.0


def test_threshold_sweep_produces_columns_app_expects():
    """
    Confirms the threshold sweep returns the fields needed
    by the dashboard.
    """
    test = pd.read_csv("data/test.csv").head(100)

    sweep = sweep_auto_contest_threshold(
        test,
        [0.5, 0.65, 0.8],
    )

    assert "threshold" in sweep.columns
    assert "precision" in sweep.columns
    assert "recall" in sweep.columns


def test_evidence_choice_mapping_matches_app_logic():
    """
    Confirms the Yes/No/Unknown mapping used by the Streamlit form.
    """
    mapping = {
        "Yes": True,
        "No": False,
        "Unknown": None,
    }

    assert mapping["Yes"] is True
    assert mapping["No"] is False
    assert mapping["Unknown"] is None


def test_dashboard_declares_five_demo_cases():
    """
    Validate the actual Python structure of demo_cases instead
    of counting arbitrary text occurrences in app_deployed.py.
    """

    source = open(
        "apps/app_deployed.py",
        encoding="utf-8",
    ).read()

    tree = ast.parse(source)

    expected_cases = {
        "CASE 1 — strong evidence",
        "CASE 2 — mixed evidence",
        "CASE 3 — network escalation",
        "CASE 4 — weak evidence",
        "CASE 5 — economic boundary",
    }

    demo_cases_node = None

    # Find:
    #
    # demo_cases = [...]
    #
    # using the Python AST rather than fragile string counting.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "demo_cases"
            ):
                demo_cases_node = node.value
                break

        if demo_cases_node is not None:
            break

    assert demo_cases_node is not None
    assert isinstance(demo_cases_node, ast.List)

    declared_cases = set()

    for item in demo_cases_node.elts:
        if not isinstance(item, ast.Tuple):
            continue

        if len(item.elts) < 1:
            continue

        first_element = item.elts[0]

        if (
            isinstance(first_element, ast.Constant)
            and isinstance(first_element.value, str)
        ):
            declared_cases.add(
                first_element.value
            )

    assert declared_cases == expected_cases

    # All five cases are rendered through the common loop.
    assert "for title, case in demo_cases:" in source

    # Streamlit expander is used for the cases.
    assert "st.expander(" in source
    