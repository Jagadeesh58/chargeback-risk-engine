"""
api.py — FastAPI backend. Contains ZERO business logic of its own.
Every decision is made by scorer.py, evidence.py, and policy.py, which
were already built and tested in Checkpoints 2-4. This file only:
  1. Validates incoming request shape (via Pydantic)
  2. Calls the already-tested pipeline functions
  3. Formats the response

If you find yourself writing an "if" statement here that makes a real
scoring or policy decision, that logic belongs in scorer.py/policy.py
instead, not here.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from scorer import predict_win_probability
from evidence import assemble
from policy import decide

app = FastAPI(title="Chargeback Risk Engine API")


class DisputeRequest(BaseModel):
    """Mirrors the real Dispute fields a caller (e.g. Razorpay's
    dashboard) would send. Field shapes match models.Dispute, per
    principle #13."""
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


@app.get("/health")
def health():
    """Simple liveness check -- no business logic, just confirms the
    server is up."""
    return {"status": "ok"}


@app.post("/score", response_model=DecisionResponse)
def score_dispute(request: DisputeRequest) -> DecisionResponse:
    dispute = request.model_dump() if hasattr(request, "model_dump") else request.dict()

    # These three calls are the ENTIRE decision -- all logic lives in
    # the already-tested modules, not here.
    win_probability = predict_win_probability(dispute)
    evidence_packet = assemble(dispute)
    decision = decide(
        win_probability=win_probability,
        amount=dispute["amount"],
        evidence_packet=evidence_packet,
    )

    return DecisionResponse(
        dispute_id=request.dispute_id,
        win_probability=win_probability,
        evidence=[
            EvidenceItemResponse(field=item.field, status=item.status)
            for item in evidence_packet.items
        ],
        action=decision.action,
        reason=decision.reason,
        expected_value=decision.expected_value,
    )