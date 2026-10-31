"""FastAPI boundary for the canonical chargeback decision service."""
import hmac
import logging
import math
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from chargeback_risk_engine.config import REASON_CODES
from chargeback_risk_engine.audit_log import verify_audit_integrity, DB_PATH, PayloadConflictError
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case

logger = logging.getLogger("chargeback_risk_engine")


def _validate_startup_config():
    env = os.getenv("CHARGEBACK_ENV", "production").lower().strip()
    if env not in ("production", "development", "demo"):
        raise RuntimeError(
            f"Invalid CHARGEBACK_ENV '{env}'. Must be one of: production, development, demo."
        )
    api_key = os.getenv("CHARGEBACK_API_KEY")
    allow_unverified_str = os.getenv("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "0").lower().strip()
    if env == "production":
        if not api_key:
            raise RuntimeError(
                "CHARGEBACK_API_KEY must be set in production mode. Set CHARGEBACK_ENV=development for local testing."
            )
        if len(api_key) < 32:
            raise RuntimeError(
                "CHARGEBACK_API_KEY must be at least 32 characters in production mode."
            )
        if allow_unverified_str in ("1", "true"):
            logger.warning(
                "SECURITY WARNING: CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE is ignored in production mode. "
                "Fail-closed provenance is strictly enforced."
            )
    else:
        if not api_key:
            logger.warning(
                "SECURITY WARNING: CHARGEBACK_API_KEY is not set. API is running in %s mode without authentication.",
                env,
            )
        if allow_unverified_str in ("1", "true"):
            logger.warning(
                "SECURITY WARNING: CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE=1 is active in %s mode. "
                "Evidence provenance verification is relaxed for local testing.",
                env,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_config()
    yield


app = FastAPI(title="Chargeback Risk Engine API", version="1.0", lifespan=lifespan)

_client_request_times: dict[str, list[float]] = defaultdict(list)
_MAX_CLIENT_ENTRIES = 5000


def _reset_rate_limiter():
    """Deterministic hook for testing rate limiting."""
    _client_request_times.clear()


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    """API key authentication dependency."""
    env = os.getenv("CHARGEBACK_ENV", "production").lower().strip()
    expected_key = os.getenv("CHARGEBACK_API_KEY")

    if env == "production":
        if not expected_key or len(expected_key) < 32:
            raise HTTPException(status_code=500, detail="API key misconfigured in production")
        if not x_api_key or not hmac.compare_digest(x_api_key.encode("utf-8"), expected_key.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return True

    # In development or demo mode
    if expected_key:
        if not x_api_key or not hmac.compare_digest(x_api_key.encode("utf-8"), expected_key.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


@app.exception_handler(PayloadConflictError)
async def payload_conflict_handler(request: Request, exc: PayloadConflictError):
    return JSONResponse(
        status_code=409,
        content={
            "error": "payload_conflict",
            "dispute_id": exc.dispute_id,
            "detail": f"Conflict: dispute_id '{exc.dispute_id}' already exists with a different payload",
        },
    )


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # 1. Rate limiting evaluated BEFORE reading body or allocating memory
    if request.url.path != "/health":
        env = os.getenv("CHARGEBACK_ENV", "production").lower().strip()
        default_limit = "60" if env == "production" else "0"
        rate_limit = int(os.getenv("CHARGEBACK_RATE_LIMIT", default_limit))
        if rate_limit > 0:
            client_ip = request.client.host if request.client else "unknown"
            x_api_key = request.headers.get("X-API-Key")
            key_id = f"key:{x_api_key[:8]}" if x_api_key else f"ip:{client_ip}"
            if os.getenv("CHARGEBACK_ALLOW_TEST_CLIENT_HEADER") == "1":
                client_id = request.headers.get("X-Client-Id", key_id)
            else:
                client_id = key_id
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
            
            # Bound memory size: evict expired clients if size exceeds threshold
            if len(_client_request_times) > _MAX_CLIENT_ENTRIES:
                expired = [k for k, v in _client_request_times.items() if not v or v[-1] <= cutoff]
                for k in expired:
                    _client_request_times.pop(k, None)

    # 2. Request body size limit (content-length header + streaming chunk abort)
    max_bytes = int(os.getenv("CHARGEBACK_MAX_BODY_BYTES", "65536"))  # default 64 KB
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})
        except ValueError:
            pass

    # Stream-read body with immediate abort for chunked transfer-encoding
    body_chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})
        body_chunks.append(chunk)
    body_bytes = b"".join(body_chunks)
    request._body = body_bytes

    return await call_next(request)


def _validate_iso_timestamp(ts_str: str | None) -> str | None:
    if ts_str is None:
        return None
    try:
        clean_ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
    except Exception as e:
        raise ValueError(f"Invalid ISO-8601 timestamp: '{ts_str}'") from e

    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Future check (allow 300 seconds clock skew)
    if (dt - now).total_seconds() > 300:
        raise ValueError(f"Timestamp cannot be in the future: '{ts_str}'")

    # Stale check
    max_age_days = float(os.getenv("CHARGEBACK_MAX_EVIDENCE_AGE_DAYS", "365"))
    if (now - dt).total_seconds() > max_age_days * 86400:
        raise ValueError(f"Timestamp is older than allowed maximum age of {max_age_days} days: '{ts_str}'")

    return ts_str


class EvidenceMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str | None = Field(default=None, max_length=128)
    timestamp: str | None = Field(default=None, max_length=64)
    consistent: bool | None = True

    @field_validator("timestamp")
    @classmethod
    def check_meta_timestamp(cls, v: str | None) -> str | None:
        return _validate_iso_timestamp(v)


class DisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispute_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payment_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    reason_code: str
    amount: float = Field(gt=0, le=100_000_000)

    customer_id: str | None = Field(default=None, max_length=128)
    device_id: str | None = Field(default=None, max_length=128)
    ip_address: str | None = Field(default=None, max_length=128)
    card_fingerprint: str | None = Field(default=None, max_length=128)
    merchant_id: str | None = Field(default=None, max_length=128)

    # Freeform narrative / prompt context (treated as raw untrusted data, never instructions)
    evidence_text: str | None = Field(default=None, max_length=10000)

    # Evidence boolean fields
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

    # Provenance fields per evidence item
    has_tracking_number_source: str | None = Field(default=None, max_length=128)
    has_tracking_number_timestamp: str | None = Field(default=None, max_length=64)
    has_tracking_number_consistent: bool | None = None

    has_delivery_confirmation_source: str | None = Field(default=None, max_length=128)
    has_delivery_confirmation_timestamp: str | None = Field(default=None, max_length=64)
    has_delivery_confirmation_consistent: bool | None = None

    has_signature_confirmation_source: str | None = Field(default=None, max_length=128)
    has_signature_confirmation_timestamp: str | None = Field(default=None, max_length=64)
    has_signature_confirmation_consistent: bool | None = None

    has_product_photos_source: str | None = Field(default=None, max_length=128)
    has_product_photos_timestamp: str | None = Field(default=None, max_length=64)
    has_product_photos_consistent: bool | None = None

    has_item_description_match_source: str | None = Field(default=None, max_length=128)
    has_item_description_match_timestamp: str | None = Field(default=None, max_length=64)
    has_item_description_match_consistent: bool | None = None

    has_return_communication_source: str | None = Field(default=None, max_length=128)
    has_return_communication_timestamp: str | None = Field(default=None, max_length=64)
    has_return_communication_consistent: bool | None = None

    has_avs_match_source: str | None = Field(default=None, max_length=128)
    has_avs_match_timestamp: str | None = Field(default=None, max_length=64)
    has_avs_match_consistent: bool | None = None

    has_cvv_match_source: str | None = Field(default=None, max_length=128)
    has_cvv_match_timestamp: str | None = Field(default=None, max_length=64)
    has_cvv_match_consistent: bool | None = None

    has_device_fingerprint_match_source: str | None = Field(default=None, max_length=128)
    has_device_fingerprint_match_timestamp: str | None = Field(default=None, max_length=64)
    has_device_fingerprint_match_consistent: bool | None = None

    has_duplicate_transaction_proof_source: str | None = Field(default=None, max_length=128)
    has_duplicate_transaction_proof_timestamp: str | None = Field(default=None, max_length=64)
    has_duplicate_transaction_proof_consistent: bool | None = None

    has_refund_already_issued_source: str | None = Field(default=None, max_length=128)
    has_refund_already_issued_timestamp: str | None = Field(default=None, max_length=64)
    has_refund_already_issued_consistent: bool | None = None

    # Global evidence provenance fields
    evidence_timestamp: str | None = Field(default=None, max_length=64)
    evidence_source_reliability: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_meta: dict[str, EvidenceMeta] | None = None

    @field_validator(
        "has_tracking_number_timestamp",
        "has_delivery_confirmation_timestamp",
        "has_signature_confirmation_timestamp",
        "has_product_photos_timestamp",
        "has_item_description_match_timestamp",
        "has_return_communication_timestamp",
        "has_avs_match_timestamp",
        "has_cvv_match_timestamp",
        "has_device_fingerprint_match_timestamp",
        "has_duplicate_transaction_proof_timestamp",
        "has_refund_already_issued_timestamp",
        "evidence_timestamp",
    )
    @classmethod
    def check_timestamp(cls, v: str | None) -> str | None:
        return _validate_iso_timestamp(v)


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
    env = os.getenv("CHARGEBACK_ENV", "production").lower().strip()
    allow_unverified = (
        env in ("development", "demo")
        and os.getenv("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "0").lower().strip() in ("1", "true")
    )
    auth_mode = "api-key" if os.getenv("CHARGEBACK_API_KEY") else ("demo-open" if env in ("development", "demo") else "unconfigured")
    return {
        "status": "ok",
        "auth": auth_mode,
        "environment": env,
        "allow_unverified_evidence": allow_unverified,
    }


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
