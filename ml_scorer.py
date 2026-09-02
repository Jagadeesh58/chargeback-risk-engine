"""
ml_scorer.py — an OPTIONAL trained Logistic Regression scorer, one
submodel per reason code (same structure that proved useful in the
earlier leakage check). Only worth keeping if it measurably beats
scorer.py's rule-based AUC on the SAME held-out test set -- not dev,
since dev already informed rule design.
"""

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from config import RELEVANT_EVIDENCE_BY_REASON, REASON_CODES


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