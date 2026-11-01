"""Reason-aware Logistic Regression used as the single live risk model.

Security Note:
Model serialization uses a safe, deterministic JSON representation
(coefficients, intercept, classes, feature ordering, and version stamps).
Arbitrary code execution via pickle is disallowed in production mode.
Integrity is strictly verified via SHA-256 sidecars (.sha256) or
the CHARGEBACK_MODEL_SHA256 environment variable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from chargeback_risk_engine.config import (
    FEATURE_VERSION,
    LIVE_MODEL_VERSION,
    REASON_CODES,
    RELEVANT_EVIDENCE_BY_REASON,
)
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR

logger = logging.getLogger("chargeback_risk_engine")

MODEL_PATH = str(ARTIFACTS_DIR / "ml_scorer_model.json")
_cached_scorer = None


def _encode_evidence(df: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    X = df[fields].copy()
    for col in fields:
        X[col] = X[col].map({True: 1.0, False: 0.0}).fillna(0.5)
    return X


class MLScorer:
    def __init__(self):
        self.models = {}
        self.model_hash: str | None = None

    def fit(self, train_df: pd.DataFrame):
        for reason in REASON_CODES:
            fields = RELEVANT_EVIDENCE_BY_REASON[reason]
            subset = train_df[train_df["reason_code"] == reason]
            X = _encode_evidence(subset, fields)
            y = subset["would_win"].astype(int)
            self.models[reason] = LogisticRegression(max_iter=1000, random_state=42).fit(X, y)
        return self

    def predict_win_probability(self, dispute: dict) -> float:
        reason = dispute["reason_code"]
        fields = RELEVANT_EVIDENCE_BY_REASON[reason]
        model = self.models[reason]
        x = [
            1.0 if dispute.get(field) is True else 0.0 if dispute.get(field) is False else 0.5
            for field in fields
        ]
        logit = float(model.intercept_[0] + sum(w * val for w, val in zip(model.coef_[0], x)))
        return float(1.0 / (1.0 + math.exp(-logit)))


def dispute_from_evidence_items(reason_code: str, evidence_items: list[dict]) -> dict:
    status_to_value = {"PASS": True, "FAIL": False, "WARN": None}
    dispute: dict[str, Any] = {"reason_code": reason_code}
    for item in evidence_items:
        dispute[item["field"]] = status_to_value[item["status"]]
    return dispute


def save_ml_scorer(path: str = MODEL_PATH, train_csv: str | None = None) -> MLScorer:
    if train_csv is None:
        train_csv = str(DATA_DIR / "train.csv")

    scorer = MLScorer().fit(pd.read_csv(train_csv))
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    bundle = {
        "model_version": LIVE_MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "sklearn_version": sklearn.__version__,
        "models": {
            reason: {
                "feature_order": list(RELEVANT_EVIDENCE_BY_REASON[reason]),
                "coef": [float(c) for c in model.coef_[0]],
                "intercept": [float(model.intercept_[0])],
                "classes": [int(c) for c in model.classes_],
            }
            for reason, model in scorer.models.items()
        },
    }

    raw_json = json.dumps(bundle, indent=2, sort_keys=True)
    json_bytes = raw_json.encode("utf-8")
    with open(path, "wb") as f:
        f.write(json_bytes)

    # Write sidecar SHA-256 for integrity verification
    digest = hashlib.sha256(json_bytes).hexdigest()
    with open(path + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write(digest.strip() + "\n")

    return scorer


def reset_cached_ml_scorer() -> None:
    """Clear memory-cached MLScorer instance."""
    global _cached_scorer
    _cached_scorer = None


def load_or_fit_ml_scorer(
    path: str = MODEL_PATH, train_csv: str | None = None, reload: bool = False
) -> MLScorer:
    global _cached_scorer
    if train_csv is None:
        train_csv = str(DATA_DIR / "train.csv")

    expected_hash = os.getenv("CHARGEBACK_MODEL_SHA256")
    if not reload and _cached_scorer is not None:
        if expected_hash and getattr(_cached_scorer, "model_hash", None) != expected_hash:
            pass  # Expected hash changed, force verification and reload!
        else:
            return _cached_scorer

    env = os.getenv("CHARGEBACK_ENV", "production").lower().strip()

    if path.endswith(".pkl"):
        raise RuntimeError(
            f"Legacy pickle model artifacts are disallowed: '{path}'. "
            "Re-train with safe JSON representation via 'make train'."
        )

    # If default json path does not exist, fit fresh and save
    effective_path = path
    if not os.path.exists(effective_path):
        _cached_scorer = save_ml_scorer(path, train_csv)
        return _cached_scorer

    with open(effective_path, "rb") as f:
        raw_bytes = f.read()

    # Integrity verification
    sidecar_path = effective_path + ".sha256"
    expected_hash = os.getenv("CHARGEBACK_MODEL_SHA256")
    if not expected_hash and os.path.exists(sidecar_path):
        with open(sidecar_path, "r", encoding="utf-8") as sf:
            expected_hash = sf.read().strip()

    actual_hash = hashlib.sha256(raw_bytes).hexdigest()
    if expected_hash:
        if actual_hash != expected_hash:
            raise ValueError(
                f"Model integrity failure: SHA-256 mismatch for {effective_path}. "
                f"Expected {expected_hash}, got {actual_hash}."
            )
    else:
        require_hash = os.getenv("CHARGEBACK_REQUIRE_MODEL_HASH", "0").lower() in ("1", "true")
        if env == "production" or require_hash:
            raise ValueError(
                f"Model integrity failure: missing required sidecar hash for {effective_path}."
            )
        logger.warning("SECURITY WARNING: Missing integrity sidecar hash for %s", effective_path)

    # Check serialization format: safe JSON only
    is_json = False
    bundle = None
    try:
        bundle = json.loads(raw_bytes.decode("utf-8"))
        if isinstance(bundle, dict) and "models" in bundle:
            is_json = True
    except (UnicodeDecodeError, json.JSONDecodeError):
        is_json = False

    if not is_json or not isinstance(bundle, dict):
        raise RuntimeError(
            f"Legacy pickle or invalid model artifact format in '{effective_path}'. "
            "Re-train with safe JSON representation via 'make train'."
        )

    # Safe JSON reconstruction
    if bundle.get("model_version") not in (None, LIVE_MODEL_VERSION):
        raise RuntimeError(f"Incompatible live model artifact: {bundle.get('model_version')}")
    if bundle.get("feature_version") not in (None, FEATURE_VERSION):
        raise RuntimeError(f"Incompatible feature artifact: {bundle.get('feature_version')}")
    if bundle.get("sklearn_version") not in (None, sklearn.__version__):
        raise RuntimeError(
            f"Live model was trained with scikit-learn {bundle.get('sklearn_version')}, "
            f"runtime has {sklearn.__version__}"
        )

    scorer = MLScorer()
    models_dict = bundle.get("models")
    if not isinstance(models_dict, dict):
        raise RuntimeError("Missing models dict in serialized model bundle")
    for reason, m_data in models_dict.items():
        lr = LogisticRegression()
        lr.coef_ = np.array([m_data["coef"]], dtype=float)
        lr.intercept_ = np.array(m_data["intercept"], dtype=float)
        lr.classes_ = np.array(m_data["classes"], dtype=int)
        scorer.models[reason] = lr

    scorer.model_hash = actual_hash
    _cached_scorer = scorer
    return _cached_scorer


def evaluate_on(df: pd.DataFrame, ml_scorer: MLScorer) -> float:
    probs = []
    for _, row in df.iterrows():
        dispute = row.to_dict()
        for key, value in dispute.items():
            if isinstance(value, float) and pd.isna(value):
                dispute[key] = None
        probs.append(ml_scorer.predict_win_probability(dispute))
    return roc_auc_score(df["would_win"], probs)


if __name__ == "__main__":
    scorer = load_or_fit_ml_scorer()
    test = pd.read_csv(DATA_DIR / "test.csv")
    print(f"Live model AUC on held-out test.csv: {evaluate_on(test, scorer):.4f}")
