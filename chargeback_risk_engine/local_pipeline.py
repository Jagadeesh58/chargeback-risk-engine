"""Local Streamlit pipeline using the same core logic as the API, enriched
with evidence intelligence, economics, graph analysis and structured explanation.
"""
from chargeback_risk_engine.engine.hybrid_pipeline import score_hybrid


def score_dispute_locally(dispute: dict) -> dict:
    return score_hybrid(dispute)
