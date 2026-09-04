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
from pydantic import BaseModel, Field

from chargeback_risk_engine.engine.hybrid_pipeline import score_hybrid
from chargeback_risk_engine.config import REASON_CODES

app = FastAPI(title="Chargeback Risk Engine API")


class DisputeRequest(BaseModel):
    """Mirrors the real Dispute fields a caller (e.g. a payments
    dashboard) would send. Field shapes match models.Dispute."""
    dispute_id: str = Field(min_length=1, max_length=128)
    payment_id: str = Field(min_length=1, max_length=128)
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
    status: str


class DecisionResponse(BaseModel):
    dispute_id: str
    win_probability: float
    calibrated_win_probability: float  # informational calibration
    rule_win_probability: float = 0.0
    # observed outcomes on dev.csv (see calibration.py) -- informational only,
    # NOT what action/reason/expected_value below were decided from
    ml_win_probability: float
    tree_model_probability: float = 0.0
    logistic_model_version: str = "logreg-v1"
    tree_model_version: str = "hgb-v1"
    # (ml_scorer.py), for live comparison against the rule-based score --
    # also informational only, policy.py never reads this
    evidence: list[EvidenceItemResponse]
    action: str
    reason: str
    expected_value: float
    replayed: bool  # True if this exact dispute_id was already decided before
    contest_draft: dict | None = None
    evidence_score: dict = {}
    graph_analysis: dict = {}
    economic_decision: dict = {}
    explanation: dict = {}
    model_version: str = "logreg-v1"
    rule_model_version: str = "rules-v1"
    feature_version: str = "features-v2"
    policy_version: str = "policy-v2"


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

    # Support both pydantic v2 (model_dump) and v1 (dict).
    dispute = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    result = score_hybrid(dispute)
    return DecisionResponse(**result)

