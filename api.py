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
    evidence: list[EvidenceItemResponse]
    action: str
    reason: str
    expected_value: float
    replayed: bool  # True if this exact dispute_id was already decided before


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

    return DecisionResponse(
        dispute_id=logged.dispute_id,
        win_probability=logged.win_probability,
        evidence=[EvidenceItemResponse(**item) for item in logged.evidence],
        action=logged.action,
        reason=logged.reason,
        expected_value=logged.expected_value,
        replayed=logged.replayed,
    )