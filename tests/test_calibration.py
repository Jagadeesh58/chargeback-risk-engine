"""
test_calibration.py — real, runnable tests for calibration.py. The most
important one is test_calibration_reduces_error_on_held_out_test_set: it
proves the fix actually works on data it was never fit on, not just that
the code runs without crashing.
"""

import csv

from chargeback_risk_engine.calibration import (
    _pava,
    apply_calibration,
    calibrated_win_probability,
    calibration_error,
    fit_calibration_points,
    load_or_fit_calibration_points,
)
from chargeback_risk_engine.scorer import predict_win_probability


def _load_pairs(csv_path):
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
            raw = predict_win_probability(dispute)
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


def test_calibration_reduces_error_on_held_out_test_set():
    """The actual proof this is worth having: fit on dev.csv, measure on
    test.csv (never touched during fitting), and confirm the calibrated
    probabilities are closer to the real observed win rate than the raw
    scorer's output."""
    points = fit_calibration_points("data/dev.csv")
    test_pairs = _load_pairs("data/test.csv")

    raw_error = calibration_error(test_pairs, points=None)
    calibrated_err = calibration_error(test_pairs, points=points)

    assert calibrated_err < raw_error, (
        f"calibration should reduce error: raw={raw_error:.4f}, "
        f"calibrated={calibrated_err:.4f}"
    )


def test_calibrated_win_probability_matches_manual_application():
    points = fit_calibration_points("data/dev.csv")
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    raw = predict_win_probability(dispute)
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
