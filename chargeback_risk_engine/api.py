"""FastAPI boundary for the canonical chargeback decision service."""
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from chargeback_risk_engine.config import REASON_CODES
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case

app = FastAPI(title="Chargeback Sentinel API", version="1.0")


class DisputeRequest(BaseModel):
    dispute_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payment_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    reason_code: str
    amount: float = Field(gt=0, le=100_000_000)

    customer_id: str | None = Field(default=None, max_length=128)
    device_id: str | None = Field(default=None, max_length=128)
    ip_address: str | None = Field(default=None, max_length=128)
    card_fingerprint: str | None = Field(default=None, max_length=128)
    merchant_id: str | None = Field(default=None, max_length=128)

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
    status: Literal["PASS", "WARN", "FAIL"]


class DecisionResponse(BaseModel):
    dispute_id: str
    reason_code: str
    amount: float
    action: Literal["AUTO-CONTEST", "HUMAN-REVIEW", "ACCEPT-LOSS"]
    win_probability: float
    calibrated_win_probability: float
    evidence: list[EvidenceItemResponse]
    evidence_score: dict
    graph_analysis: dict
    economic_decision: dict
    reason: str
    expected_value: float
    explanation: dict
    counterfactual: dict
    replayed: bool
    contest_draft: dict | None = None
    audit_id: str | None = None
    model_version: str
    policy_version: str
    feature_version: str
    live_model: str
    challenger_models: dict[str, str]


@app.get("/health")
def health():
    return {"status": "ok"}


def _score(request: DisputeRequest) -> DecisionResponse:
    if request.reason_code not in REASON_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown reason_code '{request.reason_code}'. Must be one of {REASON_CODES}.",
        )
    dispute = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return DecisionResponse(**decide_case(dispute))


@app.post("/decision", response_model=DecisionResponse)
def decision(request: DisputeRequest) -> DecisionResponse:
    """Primary decision endpoint."""
    return _score(request)


@app.post("/score", response_model=DecisionResponse, include_in_schema=False)
def score_compatibility(request: DisputeRequest) -> DecisionResponse:
    """Compatibility alias for older callers; it uses the same service."""
    return _score(request)
