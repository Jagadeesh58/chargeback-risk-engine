"""Local entry point for the same canonical decision service used by the API."""
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case


def score_dispute_locally(dispute: dict) -> dict:
    return decide_case(dispute)
