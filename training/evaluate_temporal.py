"""Temporal evaluation of the learned models and transparent hybrid recommendation."""
from pathlib import Path
import sys

# Allow direct execution from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



import sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score, f1_score, precision_score, recall_score

from chargeback_risk_engine.config import HYBRID_MODEL_WEIGHTS
from chargeback_risk_engine.scorer import predict_win_probability
from training.train_models import build_features


def metrics(y, p):
    pred = p >= 0.65
    return {
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "brier_score": float(brier_score_loss(y, p)),
    }


def main():
    df = pd.concat([pd.read_csv("data/train.csv"), pd.read_csv("data/dev.csv"), pd.read_csv("data/test.csv")], ignore_index=True)
    df["respond_by"] = pd.to_datetime(df["respond_by"])
    df = df.sort_values("respond_by").reset_index(drop=True)
    cut = int(len(df) * 0.80)
    train, test = df.iloc[:cut], df.iloc[cut:]

    X_train = build_features(train)
    X_test = build_features(test).reindex(columns=X_train.columns, fill_value=0.0)
    lr = LogisticRegression(max_iter=1000, random_state=42).fit(X_train, train["would_win"].astype(int))
    hgb = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.06, max_iter=180, random_state=42).fit(X_train, train["would_win"].astype(int))

    lr_p = lr.predict_proba(X_test)[:, 1]
    hgb_p = hgb.predict_proba(X_test)[:, 1]
    rule_p = pd.Series([predict_win_probability(r.to_dict()) for _, r in test.iterrows()]).to_numpy()
    total = sum(HYBRID_MODEL_WEIGHTS.values())
    hybrid_p = (HYBRID_MODEL_WEIGHTS["rules"] * rule_p + HYBRID_MODEL_WEIGHTS["logistic"] * lr_p + HYBRID_MODEL_WEIGHTS["tree"] * hgb_p) / total

    results = {
        "train_rows": len(train), "test_rows": len(test),
        "train_end": train["respond_by"].max().date().isoformat(),
        "test_start": test["respond_by"].min().date().isoformat(),
        "models": {"rules": metrics(test["would_win"], rule_p), "logistic_regression": metrics(test["would_win"], lr_p), "hist_gradient_boosting": metrics(test["would_win"], hgb_p), "hybrid_risk": metrics(test["would_win"], hybrid_p)},
        "hybrid_weights": HYBRID_MODEL_WEIGHTS,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/temporal_evaluation.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
