"""Reproducible comparison of rules, Logistic Regression and tree model."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
import sys

# Allow direct execution from the repository root without duplicate path setup.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd
import sklearn
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

from chargeback_risk_engine.config import (
    RELEVANT_EVIDENCE_BY_REASON,
    HYBRID_MODEL_WEIGHTS,
    LIVE_MODEL_VERSION,
    CHALLENGER_MODEL_VERSION,
    FEATURE_VERSION,
)
from chargeback_risk_engine.ml_scorer import MLScorer
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import CONTEST_COST, decide
from chargeback_risk_engine.scorer import predict_win_probability

TREE_MODEL_PATH = ARTIFACTS_DIR / "hgb_model.pkl"


def load_or_fit_tree_model(train_csv: str | Path | None = None):
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    train_csv = Path(train_csv) if train_csv is not None else DATA_DIR / "train.csv"
    if TREE_MODEL_PATH.exists():
        with TREE_MODEL_PATH.open("rb") as f:
            bundle = pickle.load(f)
        return bundle["model"], bundle["columns"]
    train = pd.read_csv(train_csv)
    model, columns = fit_model(train)
    with TREE_MODEL_PATH.open("wb") as f:
        pickle.dump(
            {
                "model": model,
                "columns": columns,
                "model_version": CHALLENGER_MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "sklearn_version": sklearn.__version__,
            },
            f,
        )
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
        values["missing_fraction"] = float(
            sum(row.get(f) is None or pd.isna(row.get(f)) for f in fields) / len(fields)
        )
        values["reason_code"] = reason
        rows.append(values)
    out = pd.DataFrame(rows).fillna(0.5)
    return pd.get_dummies(out, columns=["reason_code"], dtype=float)


def fit_model(train: pd.DataFrame):
    X = build_features(train)
    y = train["would_win"].astype(int)
    model = HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.06, max_iter=180, random_state=42
    )
    model.fit(X, y)
    return model, list(X.columns)


def predict_model(model, columns, df: pd.DataFrame) -> np.ndarray:
    X = build_features(df).reindex(columns=columns, fill_value=0.0)
    return model.predict_proba(X)[:, 1]


def rules_probs(df: pd.DataFrame) -> np.ndarray:
    return np.array([predict_win_probability(r.to_dict()) for _, r in df.iterrows()])


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
    predicted_losses = []
    for (_, row), probability in zip(test.iterrows(), hybrid):
        dispute = row.to_dict()
        packet = assemble(dispute)
        quality = score_evidence(dispute, packet)
        economic = calculate_economic_value(float(row["amount"]), float(probability))
        decision = decide(
            float(probability),
            float(row["amount"]),
            evidence_packet=packet,
            model_confidence=max(float(probability), 1.0 - float(probability)),
            expected_net_value=economic.expected_net_value,
            evidence_quality=quality,
        )
        actions.append(decision.action)
        if decision.action == "AUTO-CONTEST":
            auto_true += int(bool(row["would_win"]))
            # A false positive means we spent the flat contest cost; it does
            # not mean we lost the entire disputed amount under this policy.
            if not bool(row["would_win"]):
                fp_cost += CONTEST_COST
        predicted_losses.append(int(decision.action == "ACCEPT-LOSS"))

    human = actions.count("HUMAN-REVIEW")
    no_action = actions.count("ACCEPT-LOSS")
    auto = actions.count("AUTO-CONTEST")
    precision = auto_true / auto if auto else 0.0
    recall = auto_true / int(test["would_win"].sum()) if int(test["would_win"].sum()) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "auto_contest": {
            "count": auto,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "false_positive_cost": fp_cost,
        },
        "action_breakdown": {
            "AUTO-CONTEST": auto,
            "HUMAN-REVIEW": human,
            "ACCEPT-LOSS": no_action,
        },
        "human_review_rate": human / len(test) if len(test) else 0.0,
    }


def calibration_error(y_true, probs, bins=10):
    frac, mean = calibration_curve(y_true, probs, n_bins=bins, strategy="uniform")
    return float(np.mean(np.abs(frac - mean))) if len(frac) else 0.0


def select_live_model(dev: pd.DataFrame, models: dict[str, np.ndarray]) -> tuple[str, dict]:
    candidates = {}
    for name, probabilities in models.items():
        result = metrics(dev["would_win"], probabilities)
        result["calibration_error"] = calibration_error(dev["would_win"], probabilities)
        candidates[name] = result

    ranked_by_pr_auc = sorted(candidates, key=lambda name: candidates[name]["pr_auc"], reverse=True)
    top_pr_auc = candidates[ranked_by_pr_auc[0]]["pr_auc"]
    near_ties = [
        name for name in ranked_by_pr_auc
        if top_pr_auc - candidates[name]["pr_auc"] <= 0.01
    ]
    materially_better = [
        name for name in near_ties
        if candidates[name]["pr_auc"] >= candidates["logistic_regression"]["pr_auc"] + 0.01
    ]
    if materially_better:
        selected = min(
            materially_better,
            key=lambda name: (
                candidates[name]["brier_score"],
                candidates[name]["calibration_error"],
                {"rules": 0, "logistic_regression": 1, "hist_gradient_boosting": 2, "hybrid_risk": 3}[name],
            ),
        )
    else:
        selected = "logistic_regression"
    return selected, candidates


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=DATA_DIR / "train.csv")
    parser.add_argument("--dev", type=Path, default=DATA_DIR / "dev.csv")
    parser.add_argument("--test", type=Path, default=DATA_DIR / "test.csv")
    parser.add_argument("--output", type=Path, default=ARTIFACTS_DIR / "model_evaluation.json")
    args = parser.parse_args(argv)

    train = pd.read_csv(args.train)
    dev = pd.read_csv(args.dev)
    test = pd.read_csv(args.test)
    hgb, columns = fit_model(train)
    hgb_probs = predict_model(hgb, columns, test)
    lr_model = MLScorer().fit(train)
    from chargeback_risk_engine.ml_scorer import save_ml_scorer
    save_ml_scorer(train_csv=str(args.train))
    lr_probs = []
    for _, row in test.iterrows():
        dispute = row.to_dict()
        for key, value in dispute.items():
            if isinstance(value, float) and pd.isna(value):
                dispute[key] = None
        lr_probs.append(lr_model.predict_win_probability(dispute))
    lr_probs = np.asarray(lr_probs, dtype=float)
    rule = rules_probs(test)
    hybrid = hybrid_probs(rule, lr_probs, hgb_probs)
    dev_hgb_probs = predict_model(hgb, columns, dev)
    dev_lr_probs = np.asarray([
        lr_model.predict_win_probability(
            {
                key: (None if isinstance(value, float) and pd.isna(value) else value)
                for key, value in row.items()
            }
        )
        for row in dev.to_dict("records")
    ], dtype=float)
    dev_rule_probs = np.array([predict_win_probability(r) for r in dev.to_dict("records")])
    dev_hybrid_probs = hybrid_probs(dev_rule_probs, dev_lr_probs, dev_hgb_probs)
    selected_name, dev_selection = select_live_model(
        dev,
        {
            "rules": dev_rule_probs,
            "logistic_regression": dev_lr_probs,
            "hist_gradient_boosting": dev_hgb_probs,
            "hybrid_risk": dev_hybrid_probs,
        },
    )
    if selected_name != "logistic_regression":
        raise RuntimeError(
            f"The existing live decision path supports Logistic Regression only, "
            f"but dev-only model selection selected {selected_name}."
        )

    results = {
        "dataset": {"train": len(train), "dev": len(dev), "test": len(test)},
        "versions": {
            "live_model": LIVE_MODEL_VERSION,
            "hgb_challenger": CHALLENGER_MODEL_VERSION,
            "features": FEATURE_VERSION,
            "sklearn": sklearn.__version__,
        },
        "model_selection": {
            "selected": selected_name,
            "challengers": ["rules-v1", CHALLENGER_MODEL_VERSION, "offline-hybrid"],
            "selection_split": "dev",
            "selection_metrics": dev_selection,
            "selection_rule": "use Logistic Regression unless another candidate improves PR-AUC by at least 0.01 on dev; among qualifying alternatives prefer lower Brier score, then lower calibration error, then simpler implementation",
        },
        "models": {
            "rules": {**metrics(test["would_win"], rule), "calibration_error": calibration_error(test["would_win"], rule)},
            "logistic_regression": {**metrics(test["would_win"], lr_probs), "calibration_error": calibration_error(test["would_win"], lr_probs)},
            "hist_gradient_boosting": {**metrics(test["would_win"], hgb_probs), "calibration_error": calibration_error(test["would_win"], hgb_probs)},
            "hybrid_risk": {**metrics(test["would_win"], hybrid), "calibration_error": calibration_error(test["would_win"], hybrid)},
        },
        "final_test_split": "test is used only for final evaluation after model selection is frozen",
        "hybrid_definition": {
            "weights": HYBRID_MODEL_WEIGHTS,
            "note": "Offline challenger only; evidence/economics/policy remain deterministic safety layers.",
        },
        "hybrid_decision_system": decision_system_metrics(test, hybrid),
    }
    args.output.parent.mkdir(exist_ok=True)
    with args.output.open("w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    main()
