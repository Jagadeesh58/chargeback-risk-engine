"""FastAPI boundary for the canonical chargeback decision service."""
import hmac
import math
import os
import time
from collections import defaultdict
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from chargeback_risk_engine.config import REASON_CODES
from chargeback_risk_engine.audit_log import verify_audit_integrity, DB_PATH
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case

app = FastAPI(title="Chargeback Risk Engine API", version="1.0")

_client_request_times: dict[str, list[float]] = defaultdict(list)


def _reset_rate_limiter():
    """Deterministic hook for testing rate limiting."""
    _client_request_times.clear()


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    """Optional API key authentication dependency."""
    expected_key = os.getenv("CHARGEBACK_API_KEY")
    if expected_key:
        if not x_api_key or not hmac.compare_digest(x_api_key.encode("utf-8"), expected_key.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Request body size limit
    max_bytes = int(os.getenv("CHARGEBACK_MAX_BODY_BYTES", "65536"))  # default 64 KB
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})
        except ValueError:
            pass

    body = await request.body()
    if len(body) > max_bytes:
        return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})

    # Rate limiting
    if request.url.path != "/health":
        rate_limit = int(os.getenv("CHARGEBACK_RATE_LIMIT", "0"))
        if rate_limit > 0:
            client_ip = request.client.host if request.client else "unknown"
            client_id = request.headers.get("X-Client-Id", client_ip)
            now = time.time()
            cutoff = now - 60.0
            history = [t for t in _client_request_times[client_id] if t > cutoff]
            if len(history) >= rate_limit:
                retry_after = int(math.ceil(60.0 - (now - history[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests"},
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            history.append(now)
            _client_request_times[client_id] = history

    return await call_next(request)


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
    request_id: str = ""
    model_version: str
    policy_version: str
    feature_version: str
    live_model: str
    challenger_models: dict[str, str]


@app.get("/health")
def health():
    auth_mode = "api-key" if os.getenv("CHARGEBACK_API_KEY") else "demo-open"
    return {"status": "ok", "auth": auth_mode}


def _score(request: DisputeRequest, request_id: str | None = None) -> DecisionResponse:
    if request.reason_code not in REASON_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown reason_code '{request.reason_code}'. Must be one of {REASON_CODES}.",
        )
    dispute = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    dispute["request_id"] = request_id or dispute["dispute_id"]
    return DecisionResponse(**decide_case(dispute))


@app.post("/decision", response_model=DecisionResponse, dependencies=[Depends(require_api_key)])
def decision(request: DisputeRequest, x_request_id: str | None = Header(default=None)) -> DecisionResponse:
    """Primary decision endpoint."""
    return _score(request, x_request_id)


@app.post("/score", response_model=DecisionResponse, include_in_schema=False, dependencies=[Depends(require_api_key)])
def score_compatibility(request: DisputeRequest, x_request_id: str | None = Header(default=None)) -> DecisionResponse:
    """Compatibility alias for older callers; it uses the same service."""
    return _score(request, x_request_id)


@app.get("/audit/verify", dependencies=[Depends(require_api_key)])
def audit_verify():
    """Verify the durable SQLite audit hash chain."""
    return verify_audit_integrity(DB_PATH)
