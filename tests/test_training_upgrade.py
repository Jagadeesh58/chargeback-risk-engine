import json
from pathlib import Path

import pandas as pd

from training.train_models import build_features, fit_model, predict_model, metrics


def test_tree_model_produces_probability_and_feature_columns():
    train = pd.read_csv("data/train.csv").head(300)
    model, columns = fit_model(train)
    p = predict_model(model, columns, train.head(10))
    assert len(columns) > 0
    assert all(0.0 <= value <= 1.0 for value in p)


def test_metrics_contains_fintech_relevant_fields():
    y = pd.Series([0, 0, 1, 1])
    p = pd.Series([0.1, 0.2, 0.8, 0.9])
    result = metrics(y, p)
    for key in ["roc_auc", "pr_auc", "precision", "recall", "f1", "brier_score", "false_positive_rate", "false_negative_rate", "confusion_matrix"]:
        assert key in result
