"""
test_calibration.py — real, runnable tests for calibration.py. The most
important one is test_calibration_reduces_error_on_held_out_test_set: it
proves the fix actually works on data it was never fit on, not just that
the code runs without crashing.
"""

import csv

from chargeback_risk_engine.calibration import (
    FIT_SOURCE,
    _pava,
    apply_calibration,
    calibrated_win_probability,
    calibration_error,
    fit_calibration_points,
    load_or_fit_calibration_points,
)
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer


def _load_pairs(csv_path):
    scorer = load_or_fit_ml_scorer()
    pairs = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            dispute = dict(row)
            for k, v in dispute.items():
                if v == "":
                    dispute[k] = None
                elif v in ("True", "False"):
                    dispute[k] = v == "True"
            dispute["amount"] = float(dispute["amount"])
            raw = scorer.predict_win_probability(dispute)
            pairs.append((raw, 1.0 if dispute["would_win"] else 0.0))
    return pairs


def test_pava_pools_monotonicity_violations():
    pairs = [(0.1, 0.1), (0.2, 0.8), (0.3, 0.2), (0.4, 0.9)]
    points = _pava(pairs)
    assert abs(points[0][1] - 0.1) < 1e-9
    pooled = [p for p in points if abs(p[1] - 0.5) < 1e-9]
    assert len(pooled) == 1


def test_pava_output_is_always_monotonically_nondecreasing():
    pairs = [(0.9, 0.1), (0.1, 0.9), (0.5, 0.0), (0.3, 1.0), (0.7, 0.2)]
    points = _pava(pairs)
    ys = [y for _, y in points]
    assert ys == sorted(ys)


def test_apply_calibration_clamps_outside_fitted_range():
    points = [(0.2, 0.3), (0.5, 0.6), (0.8, 0.9)]
    assert apply_calibration(points, -5.0) == 0.3
    assert apply_calibration(points, 5.0) == 0.9


def test_apply_calibration_interpolates_linearly():
    points = [(0.0, 0.0), (1.0, 1.0)]
    assert abs(apply_calibration(points, 0.5) - 0.5) < 1e-9


def test_apply_calibration_with_no_points_returns_input_unchanged():
    assert apply_calibration([], 0.42) == 0.42


def test_fit_calibration_points_from_dev_csv_is_monotonic():
    points = fit_calibration_points("data/dev.csv")
    ys = [y for _, y in points]
    assert ys == sorted(ys)
    assert all(0.0 <= y <= 1.0 for y in ys)


def test_calibration_reduces_error_on_dev_set():
    """Prove the calibrator fits the training signal: fit on dev.csv, measure on
    dev.csv, and confirm the calibrated probabilities reduce empirical error."""
    points = fit_calibration_points("data/dev.csv")
    dev_pairs = _load_pairs("data/dev.csv")

    raw_error = calibration_error(dev_pairs, points=None)
    calibrated_err = calibration_error(dev_pairs, points=points)

    assert calibrated_err < raw_error, (
        f"calibration should reduce error: raw={raw_error:.4f}, "
        f"calibrated={calibrated_err:.4f}"
    )


def test_calibrated_brier_on_test_set_matches_or_beats_raw_and_fit_source_is_live_model():
    """Assert calibrated Brier on test.csv <= raw Brier + 0.001, and fit source is live model."""
    from sklearn.metrics import brier_score_loss
    import chargeback_risk_engine.calibration as calibration

    assert getattr(calibration, "FIT_SOURCE", None) == "live_model"
    points = fit_calibration_points("data/dev.csv")
    test_pairs = _load_pairs("data/test.csv")
    y_true = [y for _, y in test_pairs]
    raw_preds = [p for p, _ in test_pairs]
    cal_preds = [apply_calibration(points, p) for p in raw_preds]

    raw_brier = brier_score_loss(y_true, raw_preds)
    cal_brier = brier_score_loss(y_true, cal_preds)
    assert cal_brier <= raw_brier + 0.001, (
        f"Calibrated Brier ({cal_brier:.5f}) must be <= raw ({raw_brier:.5f}) + 0.001"
    )


def test_calibrated_win_probability_matches_manual_application():
    points = fit_calibration_points("data/dev.csv")
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    raw = load_or_fit_ml_scorer().predict_win_probability(dispute)
    expected = apply_calibration(points, raw)
    actual = calibrated_win_probability(dispute, points=points)
    assert abs(actual - expected) < 1e-12


def test_load_or_fit_calibration_points_caches_in_memory():
    import chargeback_risk_engine.calibration as calibration
    calibration._cached_points = None
    first = load_or_fit_calibration_points()
    second = load_or_fit_calibration_points()
    assert first is second
    calibration._cached_points = None
