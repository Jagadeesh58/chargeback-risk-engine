"""Reproducible comparison of rules, Logistic Regression and tree model."""
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
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from chargeback_risk_engine.config import REASON_CODES, RELEVANT_EVIDENCE_BY_REASON, HYBRID_MODEL_WEIGHTS
from chargeback_risk_engine.scorer import predict_win_probability
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.policy import decide

MODEL_VERSION = "chargeback-hgb-v1"
FEATURE_VERSION = "features-v2"

TREE_MODEL_PATH = "artifacts/hgb_model.pkl"

def load_or_fit_tree_model(train_csv: str = "data/train.csv"):
    Path("artifacts").mkdir(exist_ok=True)
    if Path(TREE_MODEL_PATH).exists():
        with open(TREE_MODEL_PATH, "rb") as f:
            bundle = pickle.load(f)
        return bundle["model"], bundle["columns"]
    train = pd.read_csv(train_csv)
    model, columns = fit_model(train)
    with open(TREE_MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "columns": columns, "model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION}, f)
    return model, columns


def _row_value(v):
    return 1.0 if v is True else 0.0 if v is False else 0.5


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        reason = row["reason_code"]
        fields = RELEVANT_EVIDENCE_BY_REASON[reason]
        values = {f"e_{f}": _row_value(row.get(f)) for f in fields}
        vals = [_row_value(row.get(f)) for f in fields]
        values["amount_log1p"] = float(np.log1p(max(0.0, float(row["amount"]))))
        values["evidence_mean"] = float(np.mean(vals)) if vals else 0.5
        values["missing_fraction"] = float(sum(row.get(f) is None or pd.isna(row.get(f)) for f in fields) / len(fields))
        values["reason_code"] = reason
        rows.append(values)
    out = pd.DataFrame(rows).fillna(0.5)
    out = pd.get_dummies(out, columns=["reason_code"], dtype=float)
    return out


def fit_model(train: pd.DataFrame):
    X = build_features(train)
    y = train["would_win"].astype(int)
    model = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.06, max_iter=180, random_state=42)
    model.fit(X, y)
    return model, list(X.columns)


def predict_model(model, columns, df: pd.DataFrame) -> np.ndarray:
    X = build_features(df).reindex(columns=columns, fill_value=0.0)
    return model.predict_proba(X)[:, 1]


def rules_probs(df: pd.DataFrame) -> np.ndarray:
    return np.array([predict_win_probability(r.to_dict()) for _, r in df.iterrows()])


def logistic_probs(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    X_train = build_features(train)
    X_test = build_features(test).reindex(columns=X_train.columns, fill_value=0.0)
    model = LogisticRegression(max_iter=1000, random_state=42)
    model.fit(X_train, train["would_win"].astype(int))
    return model.predict_proba(X_test)[:, 1]


def hybrid_probs(rule_probs: np.ndarray, lr_probs: np.ndarray, tree_probs: np.ndarray) -> np.ndarray:
    w = HYBRID_MODEL_WEIGHTS
    total = sum(w.values())
    return (w["rules"] * rule_probs + w["logistic"] * lr_probs + w["tree"] * tree_probs) / total


def metrics(y_true, probs, threshold=0.65):
    pred = probs >= threshold
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "roc_auc": float(roc_auc_score(y_true, probs)),
        "pr_auc": float(average_precision_score(y_true, probs)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, probs)),
        "false_positive_rate": float(fp / (fp + tn) if fp + tn else 0.0),
        "false_negative_rate": float(fn / (fn + tp) if fn + tp else 0.0),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def decision_system_metrics(test: pd.DataFrame, hybrid: np.ndarray) -> dict:
    actions = []
    fp_cost = 0.0
    auto_true = 0
    auto_total = 0
    predicted_losses = []
    for (_, row), probability in zip(test.iterrows(), hybrid):
        dispute = row.to_dict()
        packet = assemble(dispute)
        quality = score_evidence(dispute, packet)
        economic = calculate_economic_value(float(row["amount"]), float(probability))
        decision = decide(
            float(probability), float(row["amount"]), evidence_packet=packet,
            model_confidence=max(float(probability), 1.0 - float(probability)),
            expected_net_value=economic.expected_net_value,
            evidence_quality=quality,
        )
        actions.append(decision.action)
        if decision.action == "AUTO-CONTEST":
            auto_total += 1
            actual = bool(row["would_win"])
            auto_true += int(actual)
            if not actual:
                fp_cost += float(row["amount"])
        predicted_losses.append(int(decision.action == "ACCEPT LOSS"))
    human = actions.count("HUMAN REVIEW")
    no_action = actions.count("ACCEPT LOSS")
    auto = actions.count("AUTO-CONTEST")
    precision = auto_true / auto if auto else 0.0
    recall = auto_true / int(test["would_win"].sum()) if int(test["would_win"].sum()) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "auto_contest": {"count": auto, "precision": precision, "recall": recall, "f1": f1, "false_positive_cost": fp_cost},
        "action_breakdown": {"AUTO-CONTEST": auto, "HUMAN REVIEW": human, "ACCEPT LOSS": no_action},
        "human_review_rate": human / len(test) if len(test) else 0.0,
    }


def calibration_error(y_true, probs, bins=10):
    frac, mean = calibration_curve(y_true, probs, n_bins=bins, strategy="uniform")
    return float(np.mean(np.abs(frac - mean))) if len(frac) else 0.0


def main():
    train = pd.read_csv("data/train.csv")
    dev = pd.read_csv("data/dev.csv")
    test = pd.read_csv("data/test.csv")
    hgb, columns = fit_model(train)
    hgb_probs = predict_model(hgb, columns, test)
    lr_probs = logistic_probs(train, test)
    rule = rules_probs(test)
    hybrid = hybrid_probs(rule, lr_probs, hgb_probs)
    results = {
        "dataset": {"train": len(train), "dev": len(dev), "test": len(test)},
        "versions": {"model": MODEL_VERSION, "features": FEATURE_VERSION},
        "models": {
            "rules": {**metrics(test["would_win"], rule), "calibration_error": calibration_error(test["would_win"], rule)},
            "logistic_regression": {**metrics(test["would_win"], lr_probs), "calibration_error": calibration_error(test["would_win"], lr_probs)},
            "hist_gradient_boosting": {**metrics(test["would_win"], hgb_probs), "calibration_error": calibration_error(test["would_win"], hgb_probs)},
            "hybrid_risk": {**metrics(test["would_win"], hybrid), "calibration_error": calibration_error(test["would_win"], hybrid)},
        },
        "hybrid_definition": {"weights": HYBRID_MODEL_WEIGHTS, "note": "Probability recommendation only; evidence/economics/policy remain deterministic safety layers."},
        "hybrid_decision_system": decision_system_metrics(test, hybrid),
    }
    out = Path("artifacts")
    out.mkdir(exist_ok=True)
    with open(out / "model_evaluation.json", "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
