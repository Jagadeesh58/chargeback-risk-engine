"""
api.py — FastAPI backend. Contains ZERO business logic of its own.
Every decision is made by scorer.py, evidence.py, and policy.py, which
are already built and tested separately. This file only:
  1. Validates incoming request shape (via Pydantic)
  2. Calls the already-tested pipeline functions
  3. Formats the response

If you find yourself writing an "if" statement here that makes a real
scoring or policy decision, that logic belongs in scorer.py/policy.py
instead, not here.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import REASON_CODES
from scorer import predict_win_probability
from evidence import assemble
from policy import decide
from audit_log import get_or_create_decision
from razorpay_adapter import generate_contest_draft
from calibration import apply_calibration, load_or_fit_calibration_points

app = FastAPI(title="Chargeback Risk Engine API")


class DisputeRequest(BaseModel):
    """Mirrors the real Dispute fields a caller (e.g. a payments
    dashboard) would send. Field shapes match models.Dispute."""
    dispute_id: str
    payment_id: str
    reason_code: str
    amount: float

    has_tracking_number: bool | None = None
    has_delivery_confirmation: bool | None = None
    has_signature_confirmation: bool | None = None
    has_product_photos: bool | None = None
    has_item_description_match: bool | None = None
    has_return_communication: bool | None = None
    has_avs_match: bool | None = None
    has_cvv_match: bool | None = None
    has_device_fingerprint_match: bool | None = None
    has_duplicate_transaction_proof: bool | None = None
    has_refund_already_issued: bool | None = None


class EvidenceItemResponse(BaseModel):
    field: str
    status: str


class DecisionResponse(BaseModel):
    dispute_id: str
    win_probability: float
    calibrated_win_probability: float  # win_probability corrected against real
    # observed outcomes on dev.csv (see calibration.py) -- informational only,
    # NOT what action/reason/expected_value below were decided from
    evidence: list[EvidenceItemResponse]
    action: str
    reason: str
    expected_value: float
    replayed: bool  # True if this exact dispute_id was already decided before
    contest_draft: dict | None = None  # only populated for AUTO-CONTEST; always a
    # DRAFT in Razorpay's evidence-submission shape, never auto-submitted


@app.get("/health")
def health():
    """Simple liveness check -- no business logic, just confirms the
    server is up."""
    return {"status": "ok"}


@app.post("/score", response_model=DecisionResponse)
def score_dispute(request: DisputeRequest) -> DecisionResponse:
    # Validated here, not left to fall through to scorer.py's dict lookup --
    # an unknown reason_code would otherwise raise an unhandled KeyError
    # deep in the pipeline (a 500), instead of a clean 422 at the door.
    if request.reason_code not in REASON_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown reason_code '{request.reason_code}'. "
                   f"Must be one of {REASON_CODES}.",
        )

    # Support both pydantic v2 (model_dump) and v1 (dict) -- different
    # machines may have different versions installed already.
    dispute = request.model_dump() if hasattr(request, "model_dump") else request.dict()

    def compute():
        # These three calls are the ENTIRE decision -- all logic lives in
        # the already-tested modules, not here. Only invoked if this
        # dispute_id has never been decided before (see audit_log.py).
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
        dispute_id=request.dispute_id,
        reason_code=request.reason_code,
        amount=request.amount,
        compute_decision_fn=compute,
    )

    # A contest draft only makes sense when the decision was to contest.
    # Recomputed fresh from the logged decision rather than stored in the
    # audit log -- generate_contest_draft() is deterministic given the
    # same inputs, so a replayed decision still gets a byte-identical
    # draft without needing a database schema change to persist it.
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

    return DecisionResponse(
        dispute_id=logged.dispute_id,
        win_probability=logged.win_probability,
        calibrated_win_probability=calibrated_probability,
        evidence=[EvidenceItemResponse(**item) for item in logged.evidence],
        action=logged.action,
        reason=logged.reason,
        expected_value=logged.expected_value,
        replayed=logged.replayed,
        contest_draft=contest_draft,
    )