"""
ml_scorer.py — an OPTIONAL trained Logistic Regression scorer, one
submodel per reason code (same structure that proved useful in the
earlier leakage check). Only worth keeping if it measurably beats
scorer.py's rule-based AUC on the SAME held-out test set -- not dev,
since dev already informed rule design.
"""

import os
import pickle

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from config import RELEVANT_EVIDENCE_BY_REASON, REASON_CODES

MODEL_PATH = "ml_scorer_model.pkl"

_cached_scorer = None


def _encode_evidence(df: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    """True->1.0, False->0.0, missing/None->0.5 (neutral), matching the
    same encoding scheme used in verify_no_leakage.py."""
    X = df[fields].copy()
    for col in fields:
        X[col] = X[col].map({True: 1.0, False: 0.0}).fillna(0.5)
    return X


class MLScorer:
    """Trains one LogisticRegression per reason code on train.csv,
    exposes predict_win_probability(dispute) with the SAME interface as
    scorer.predict_win_probability, so it's a drop-in comparison."""

    def __init__(self):
        self.models = {}

    def fit(self, train_df: pd.DataFrame):
        for reason in REASON_CODES:
            fields = RELEVANT_EVIDENCE_BY_REASON[reason]
            subset = train_df[train_df["reason_code"] == reason]
            X = _encode_evidence(subset, fields)
            y = subset["would_win"].astype(int)
            model = LogisticRegression(max_iter=1000)
            model.fit(X, y)
            self.models[reason] = model
        return self

    def predict_win_probability(self, dispute: dict) -> float:
        reason = dispute["reason_code"]
        fields = RELEVANT_EVIDENCE_BY_REASON[reason]
        model = self.models[reason]

        row = {}
        for f in fields:
            v = dispute.get(f)
            row[f] = 1.0 if v is True else (0.0 if v is False else 0.5)
        X = pd.DataFrame([row])[fields]
        return float(model.predict_proba(X)[0, 1])


def dispute_from_evidence_items(reason_code: str, evidence_items: list[dict]) -> dict:
    """Reconstructs a dispute-shaped dict from an already-assembled
    evidence packet's PASS/WARN/FAIL items (the shape audit_log.py
    stores), so predict_win_probability() can be called against a
    durably-logged decision rather than a live, possibly-mutated
    request -- the same reasoning razorpay_adapter.py's draft
    generation already relies on for idempotent replay."""
    status_to_value = {"PASS": True, "FAIL": False, "WARN": None}
    dispute = {"reason_code": reason_code}
    for item in evidence_items:
        dispute[item["field"]] = status_to_value[item["status"]]
    return dispute


def load_or_fit_ml_scorer(path: str = MODEL_PATH, train_csv: str = "train.csv") -> MLScorer:
    """Loads a previously-fitted, pickled scorer if one exists; otherwise
    trains fresh on train.csv and saves it, so a clean clone with no
    prior run still works with zero setup. Cached in-process so a live
    server doesn't refit on every request."""
    global _cached_scorer
    if _cached_scorer is not None:
        return _cached_scorer

    if os.path.exists(path):
        with open(path, "rb") as f:
            _cached_scorer = pickle.load(f)
    else:
        train_df = pd.read_csv(train_csv)
        _cached_scorer = MLScorer().fit(train_df)
        with open(path, "wb") as f:
            pickle.dump(_cached_scorer, f)
    return _cached_scorer


def evaluate_on(df: pd.DataFrame, ml_scorer: MLScorer) -> float:
    """Returns AUC of the ML scorer on the given dataframe."""
    probs = []
    for _, row in df.iterrows():
        dispute = row.to_dict()
        for k, v in dispute.items():
            if isinstance(v, float) and pd.isna(v):
                dispute[k] = None
        probs.append(ml_scorer.predict_win_probability(dispute))
    return roc_auc_score(df["would_win"], probs)


if __name__ == "__main__":
    scorer = load_or_fit_ml_scorer()
    test = pd.read_csv("test.csv")
    print(f"Trained on train.csv, saved to {MODEL_PATH}")
    print(f"AUC on held-out test.csv: {evaluate_on(test, scorer):.4f}")