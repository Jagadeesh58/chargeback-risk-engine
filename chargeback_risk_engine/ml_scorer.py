"""Reason-aware Logistic Regression used as the single live risk model."""
from __future__ import annotations

import os
import pickle

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

MODEL_PATH = str(ARTIFACTS_DIR / "ml_scorer_model.pkl")
_cached_scorer = None


def _encode_evidence(df: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    X = df[fields].copy()
    for col in fields:
        X[col] = X[col].map({True: 1.0, False: 0.0}).fillna(0.5)
    return X


class MLScorer:
    def __init__(self):
        self.models = {}

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
        row = {
            field: 1.0 if dispute.get(field) is True else 0.0 if dispute.get(field) is False else 0.5
            for field in fields
        }
        return float(model.predict_proba(pd.DataFrame([row])[fields])[0, 1])


def dispute_from_evidence_items(reason_code: str, evidence_items: list[dict]) -> dict:
    status_to_value = {"PASS": True, "FAIL": False, "WARN": None}
    dispute = {"reason_code": reason_code}
    for item in evidence_items:
        dispute[item["field"]] = status_to_value[item["status"]]
    return dispute


def save_ml_scorer(path: str = MODEL_PATH, train_csv: str | None = None) -> MLScorer:
    if train_csv is None:
        train_csv = str(DATA_DIR / "train.csv")

    scorer = MLScorer().fit(pd.read_csv(train_csv))
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(
            {
                "scorer": scorer,
                "model_version": LIVE_MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "sklearn_version": sklearn.__version__,
            },
            f,
        )
    return scorer


def load_or_fit_ml_scorer(path: str = MODEL_PATH, train_csv: str | None = None) -> MLScorer:
    global _cached_scorer
    if train_csv is None:
        train_csv = str(DATA_DIR / "train.csv")
    if _cached_scorer is not None:
        return _cached_scorer

    if os.path.exists(path):
        with open(path, "rb") as f:
            bundle = pickle.load(f)
        if isinstance(bundle, dict) and "scorer" in bundle:
            if bundle.get("model_version") not in (None, LIVE_MODEL_VERSION):
                raise RuntimeError(f"Incompatible live model artifact: {bundle.get('model_version')}")
            if bundle.get("feature_version") not in (None, FEATURE_VERSION):
                raise RuntimeError(f"Incompatible feature artifact: {bundle.get('feature_version')}")
            if bundle.get("sklearn_version") not in (None, sklearn.__version__):
                raise RuntimeError(
                    f"Live model was trained with scikit-learn {bundle.get('sklearn_version')}, "
                    f"runtime has {sklearn.__version__}"
                )
            _cached_scorer = bundle["scorer"]
        else:
            _cached_scorer = bundle
    else:
        _cached_scorer = save_ml_scorer(path, train_csv)
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
