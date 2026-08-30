"""
local_pipeline.py — the same pipeline call api.py makes over HTTP,
available as a plain function with zero UI code mixed in. Used by
app_deployed.py so the deployed Streamlit app needs no separate server.
Kept separate from app_deployed.py specifically so this logic can be
imported and tested without triggering Streamlit's page rendering.
"""

from scorer import predict_win_probability
from evidence import assemble
from policy import decide
from audit_log import get_or_create_decision


def score_dispute_locally(dispute: dict) -> dict:
    """The exact same three calls api.py makes -- scorer -> evidence ->
    policy -- plus the same audit_log idempotency guarantee. No business
    logic lives here; it only orchestrates calls to already-tested
    modules, identical to what api.py does over HTTP."""
    def compute():
        win_probability = predict_win_probability(dispute)
        evidence_packet = assemble(dispute)
        decision = decide(
            win_probability=win_probability,
            amount=dispute["amount"],
            evidence_packet=evidence_packet,
        )
        evidence_list = [
            {"field": item.field, "status": item.status}
            for item in evidence_packet.items
        ]
        return win_probability, evidence_list, decision.action, decision.reason, decision.expected_value

    logged = get_or_create_decision(
        dispute_id=dispute["dispute_id"],
        reason_code=dispute["reason_code"],
        amount=dispute["amount"],
        compute_decision_fn=compute,
    )
    return {
        "win_probability": logged.win_probability,
        "evidence": logged.evidence,
        "action": logged.action,
        "reason": logged.reason,
        "expected_value": logged.expected_value,
        "replayed": logged.replayed,
    }