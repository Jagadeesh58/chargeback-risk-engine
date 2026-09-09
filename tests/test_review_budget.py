import pandas as pd
from chargeback_risk_engine.review_budget import optimize_review_budget


def test_review_budget_returns_configured_capacities():
    results = pd.DataFrame([
        {"action":"HUMAN-REVIEW","expected_net_value":100,"p_win":0.55,"amount":2000,"pass_count":2,"evidence_total":3,"would_win":True},
        {"action":"HUMAN-REVIEW","expected_net_value":80,"p_win":0.50,"amount":1500,"pass_count":1,"evidence_total":3,"would_win":False},
        {"action":"AUTO-CONTEST","expected_net_value":400,"p_win":0.90,"amount":3000,"pass_count":3,"evidence_total":3,"would_win":True},
    ])
    out = optimize_review_budget(results, [0.5, 1.0])
    assert list(out["review_budget"]) == [0.5, 1.0]
    assert list(out["capacity"]) == [1, 3]
