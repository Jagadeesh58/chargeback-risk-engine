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
from razorpay_adapter import generate_contest_draft
from calibration import apply_calibration, load_or_fit_calibration_points
from ml_scorer import dispute_from_evidence_items, load_or_fit_ml_scorer


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

    contest_draft = None
    if logged.action == "AUTO-CONTEST":
        contest_draft = generate_contest_draft(
            dispute_id=logged.dispute_id,
            amount=logged.amount,
            evidence_items=logged.evidence,
            summary=logged.reason,
        )

    calibration_points = load_or_fit_calibration_points()
    calibrated_probability = apply_calibration(calibration_points, logged.win_probability)

    ml_scorer_instance = load_or_fit_ml_scorer()
    ml_dispute = dispute_from_evidence_items(logged.reason_code, logged.evidence)
    ml_probability = ml_scorer_instance.predict_win_probability(ml_dispute)

    return {
        "win_probability": logged.win_probability,
        "calibrated_win_probability": calibrated_probability,
        "ml_win_probability": ml_probability,
        "evidence": logged.evidence,
        "action": logged.action,
        "reason": logged.reason,
        "expected_value": logged.expected_value,
        "replayed": logged.replayed,
        "contest_draft": contest_draft,
    }