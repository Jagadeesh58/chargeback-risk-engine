"""
calibration.py — fixes a real, documented weakness: scorer.py's raw
probabilities rank disputes reasonably (AUC 0.688) but aren't
well-calibrated -- underconfident at the low end, overconfident at the
high end (see `docs/MODEL_CARD.md` for calibration scope and limitations). This module
fits an isotonic regression
(a monotonic, data-driven curve, not hand-picked) mapping the raw score
to an actual observed win rate, using dev.csv -- the same split
scorer.py's threshold was NOT tuned against test.csv on, so this stays
consistent with keeping test.csv held out for final reporting only.

Deliberately NOT wired into policy.py. The routing decision
(AUTO-CONTEST / HUMAN-REVIEW / ACCEPT-LOSS) keeps using the raw model estimate
it was already fuzz-tested and threshold-tuned against -- changing what
number the ceiling/threshold checks see would require re-validating
everything in test_policy.py under new semantics. Calibration is
exposed as a second, separate number instead: more useful than the raw
score specifically for a human looking at a HUMAN-REVIEW case and
wanting an accurate probability, not a ranking.

Implemented as isotonic regression via the Pool Adjacent Violators
Algorithm (PAVA), by hand, rather than importing scikit-learn's
IsotonicRegression -- this project already depends on scikit-learn
elsewhere (ml_scorer.py), but PAVA is short enough to write directly and
review line by line, consistent with this project's general preference
for code that can be fully explained over an opaque library call.
"""

import csv
import json
import logging
import math
import os
from typing import Any

from chargeback_risk_engine.paths import DATA_DIR, ARTIFACTS_DIR

logger = logging.getLogger("chargeback_risk_engine")

CALIBRATION_POINTS_PATH = str(ARTIFACTS_DIR / "calibration_points.json")
FIT_SOURCE = "live_model"

_cached_points = None
_calibration_metadata = {
    "valid": True,
    "error": None,
    "fallback_to_raw": False,
    "source": CALIBRATION_POINTS_PATH,
}


def get_calibration_metadata() -> dict[str, Any]:
    """Return the current calibration validation and fallback status."""
    return dict(_calibration_metadata)


def validate_calibration_points(points: Any) -> tuple[bool, str | None]:
    """Validate calibration points against schema, bounds, and monotonicity constraints.

    Requires:
    1. List of 2-element pairs (x, y)
    2. Finite numeric values
    3. x in [0, 1] and y in [0, 1]
    4. Monotonically non-decreasing y values (and non-decreasing x)
    """
    if not isinstance(points, (list, tuple)):
        return False, "Calibration points must be a list or tuple of pairs."
    if not points:
        return False, "Calibration points list is empty."
    last_x = -1.0
    last_y = -1.0
    for idx, item in enumerate(points):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return False, f"Item at index {idx} is not a 2-element pair: {item}."
        x, y = item
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            return False, f"Item at index {idx} contains non-numeric values: ({x}, {y})."
        if not (math.isfinite(x) and math.isfinite(y)):
            return False, f"Item at index {idx} contains non-finite values: ({x}, {y})."
        if not (0.0 <= x <= 1.0):
            return False, f"Item at index {idx} has x outside [0, 1]: {x}."
        if not (0.0 <= y <= 1.0):
            return False, f"Item at index {idx} has y outside [0, 1]: {y}."
        if x < last_x - 1e-9:
            return False, f"Item at index {idx} violates non-decreasing x: {x} < {last_x}."
        if y < last_y - 1e-9:
            return False, f"Item at index {idx} violates monotonic non-decreasing y: {y} < {last_y}."
        last_x = float(x)
        last_y = float(y)
    return True, None


def _pava(pairs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """
    Pool Adjacent Violators Algorithm. Given (x, y) pairs, returns a
    smaller list of (x_center, y_value) points describing the best-fit
    monotonically non-decreasing step function, in the least-squares
    sense. Each returned point represents one "pooled" block of the
    original points, merged wherever the raw data would otherwise have
    made the fit go down as x increases.
    """
    if not pairs:
        return []
    # Pre-aggregate identical / near-identical x values for proper tie handling
    x_grouped = {}
    for x, y in sorted(pairs, key=lambda p: p[0]):
        x_key = round(x, 8)
        if x_key not in x_grouped:
            x_grouped[x_key] = [0.0, 0, x, x]
        x_grouped[x_key][0] += y
        x_grouped[x_key][1] += 1
    blocks = list(x_grouped.values())

    i = 0
    while i < len(blocks) - 1:
        avg_i = blocks[i][0] / blocks[i][1]
        avg_next = blocks[i + 1][0] / blocks[i + 1][1]
        if avg_i > avg_next:
            merged = [
                blocks[i][0] + blocks[i + 1][0],
                blocks[i][1] + blocks[i + 1][1],
                blocks[i][2],
                blocks[i + 1][3],
            ]
            blocks[i:i + 2] = [merged]
            i = max(i - 1, 0)
        else:
            i += 1

    return [((b[2] + b[3]) / 2.0, b[0] / b[1]) for b in blocks]


def apply_calibration(points: list[tuple[float, float]], raw_probability: float) -> float:
    """Linear interpolation between fitted points; clamped at the ends.

    If points are missing or fail validation, falls back safely to raw_probability.
    """
    if not points:
        return raw_probability
    is_valid, _ = validate_calibration_points(points)
    if not is_valid:
        return raw_probability
    if raw_probability <= points[0][0]:
        return points[0][1]
    if raw_probability >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= raw_probability <= x1:
            if x1 == x0:
                return y0
            t = (raw_probability - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[-1][1]


def fit_calibration_points(dev_csv_path: str | None = None) -> list[tuple[float, float]]:
    if dev_csv_path is None:
        dev_csv_path = str(DATA_DIR / "dev.csv")
    """Reads dev.csv, scores every row with the live logistic ML model,
    pairs each raw probability with the real would_win outcome,
    and fits the isotonic curve. This is the "training" step -- it never
    touches test.csv."""
    from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer

    scorer = load_or_fit_ml_scorer()
    pairs = []
    with open(dev_csv_path, newline="") as f:
        for row in csv.DictReader(f):
            dispute = dict(row)
            for k, v in dispute.items():
                if v == "":
                    dispute[k] = None
                elif v in ("True", "False"):
                    dispute[k] = v == "True"
            dispute["amount"] = float(dispute["amount"])
            raw = scorer.predict_win_probability(dispute)
            would_win = 1.0 if dispute["would_win"] else 0.0
            pairs.append((raw, would_win))

    return _pava(pairs)


def save_calibration_points(points: list[tuple[float, float]], path: str = CALIBRATION_POINTS_PATH) -> None:
    with open(path, "w") as f:
        json.dump(points, f, indent=2)


def load_or_fit_calibration_points(path: str = CALIBRATION_POINTS_PATH,
                                     dev_csv_path: str | None = None) -> list[tuple[float, float]]:
    """Loads a saved fit if one exists; otherwise fits fresh from dev.csv
    and saves it, so a clean clone with no prior run still works with
    zero setup.

    Validates calibration points against schema, bounds, and monotonicity.
    On validation failure, falls back safely to raw probability and flags in metadata.
    """
    global _cached_points, _calibration_metadata
    if _cached_points is not None:
        return _cached_points

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            is_valid, err = validate_calibration_points(loaded)
            if not is_valid:
                logger.warning(
                    "Calibration validation failed for %s: %s; falling back to raw probability.",
                    path,
                    err,
                )
                _calibration_metadata = {
                    "valid": False,
                    "error": err,
                    "fallback_to_raw": True,
                    "source": path,
                }
                _cached_points = []
                return []
            _calibration_metadata = {
                "valid": True,
                "error": None,
                "fallback_to_raw": False,
                "source": path,
            }
            _cached_points = [tuple(p) for p in loaded]
        except Exception as e:
            logger.warning(
                "Error reading calibration file %s: %s; falling back to raw probability.",
                path,
                e,
            )
            _calibration_metadata = {
                "valid": False,
                "error": str(e),
                "fallback_to_raw": True,
                "source": path,
            }
            _cached_points = []
            return []
    else:
        _cached_points = fit_calibration_points(dev_csv_path)
        save_calibration_points(_cached_points, path)
        _calibration_metadata = {
            "valid": True,
            "error": None,
            "fallback_to_raw": False,
            "source": path,
        }
    return _cached_points


def calibrated_win_probability(dispute: dict, points: list[tuple[float, float]] | None = None) -> float:
    """Convenience wrapper: raw score -> calibrated probability, for a
    single dispute dict, using the cached/fitted calibration curve."""
    from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer

    if points is None:
        points = load_or_fit_calibration_points()
    raw = load_or_fit_ml_scorer().predict_win_probability(dispute)
    return apply_calibration(points, raw)


def calibration_error(pairs: list[tuple[float, float]], points: list[tuple[float, float]] | None,
                        n_bins: int = 5) -> float:
    """Mean absolute difference between average predicted probability and
    actual observed win rate, across n_bins equal-width bins of the raw
    score -- the same shape of check as metrics.calibration_check(), but
    reduced to one number so before/after calibration can be compared
    directly. Pass points=None to measure the raw, uncalibrated score."""
    if not pairs:
        return 0.0
    bins = [[] for _ in range(n_bins)]
    for raw, would_win in pairs:
        predicted = raw if points is None else apply_calibration(points, raw)
        idx = min(int(raw * n_bins), n_bins - 1)
        bins[idx].append((predicted, would_win))

    errors = []
    for b in bins:
        if not b:
            continue
        avg_predicted = sum(p for p, _ in b) / len(b)
        avg_actual = sum(w for _, w in b) / len(b)
        errors.append(abs(avg_predicted - avg_actual))
    return sum(errors) / len(errors) if errors else 0.0


if __name__ == "__main__":
    points = fit_calibration_points(str(DATA_DIR / "dev.csv"))
    save_calibration_points(points)
    print(f"Fitted {len(points)} calibration points from dev.csv, saved to {CALIBRATION_POINTS_PATH}")
    print(points)
