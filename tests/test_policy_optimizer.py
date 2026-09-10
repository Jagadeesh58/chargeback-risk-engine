import pandas as pd
from chargeback_risk_engine.policy_optimizer import evaluate_threshold


def test_threshold_evaluation_is_deterministic():
    dev = pd.read_csv("data/dev.csv").head(50)
    p = dev["would_win"].astype(float).to_numpy() * 0.6 + 0.2
    a = evaluate_threshold(dev, p, 0.65)
    b = evaluate_threshold(dev, p, 0.65)
    assert a == b
    assert 0.0 <= a["precision"] <= 1.0
    assert 0.0 <= a["recall"] <= 1.0
