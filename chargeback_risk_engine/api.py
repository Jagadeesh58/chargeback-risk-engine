"""FastAPI boundary for the canonical chargeback decision service."""

from __future__ import annotations

import asyncio
import hmac
import logging
import math
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from chargeback_risk_engine.audit_log import (
    DB_PATH,
    PayloadConflictError,
    verify_audit_integrity,
    _get_connection,
)
from chargeback_risk_engine.config import REASON_CODES
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.observability import (
    AUDIT_WRITES_TOTAL,
    CONTENT_TYPE_LATEST,
    DECISIONS_TOTAL,
    DECISION_DURATION_SECONDS,
    EVIDENCE_SCORES,
    RATE_LIMIT_EXCEEDED_TOTAL,
    configure_logging,
    current_request_id,
    generate_latest,
)
from chargeback_risk_engine.settings import KeyInfo, get_settings, reset_settings

logger = logging.getLogger("chargeback_risk_engine")


def _validate_startup_config() -> None:
    """Validate runtime environment and configuration at startup."""
    settings = reset_settings()
    settings.validate_startup()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _validate_startup_config()
    yield


app = FastAPI(
    title="Chargeback Risk Engine API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_client_request_times: dict[str, list[float]] = defaultdict(list)
_MAX_CLIENT_ENTRIES = 5000


def _reset_rate_limiter() -> None:
    """Deterministic hook for testing rate limiting."""
    _client_request_times.clear()


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> KeyInfo:
    """API key authentication dependency resolving actor identity and scope."""
    settings = get_settings()
    env = settings.env.lower().strip()
    configured_keys = settings.get_parsed_api_keys()

    if env == "production":
        if not configured_keys:
            raise HTTPException(status_code=500, detail="API key misconfigured in production")
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        for secret, info in configured_keys.items():
            if hmac.compare_digest(x_api_key.encode("utf-8"), secret.encode("utf-8")):
                return info

        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    # In development or demo mode
    if configured_keys:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        for secret, info in configured_keys.items():
            if hmac.compare_digest(x_api_key.encode("utf-8"), secret.encode("utf-8")):
                return info
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    # Open unauthenticated dev mode
    return KeyInfo(key_id="anonymous", secret="", role="decision")


def require_decision_scope(
    key_info: KeyInfo = Depends(require_api_key),
) -> KeyInfo:
    """Authorize write/decision actions; blocks read-only keys."""
    if key_info.role == "readonly":
        raise HTTPException(
            status_code=403,
            detail="Read-only API key cannot perform decision operations",
        )
    return key_info


@app.exception_handler(PayloadConflictError)
async def payload_conflict_handler(request: Request, exc: PayloadConflictError):
    AUDIT_WRITES_TOTAL.labels(status="conflict").inc()
    return JSONResponse(
        status_code=409,
        content={
            "error": "payload_conflict",
            "dispute_id": exc.dispute_id,
            "detail": f"Conflict: dispute_id '{exc.dispute_id}' already exists with a different payload",
        },
    )


@app.middleware("http")
async def request_context_and_security_middleware(request: Request, call_next):
    # 1. Request ID tracking
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = current_request_id.set(req_id)

    # 2. Rate limiting evaluated BEFORE reading body or allocating memory
    if request.url.path not in ("/health", "/healthz", "/readyz", "/metrics"):
        settings = get_settings()
        env = settings.env.lower().strip()
        default_limit = 60 if env == "production" else 0
        rate_limit = int(os.getenv("CHARGEBACK_RATE_LIMIT", str(settings.rate_limit if settings.rate_limit != 60 else default_limit)))
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
                RATE_LIMIT_EXCEEDED_TOTAL.labels(key_id=client_id).inc()
                retry_after = int(math.ceil(60.0 - (now - history[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests"},
                    headers={
                        "Retry-After": str(max(1, retry_after)),
                        "X-Request-ID": req_id,
                    },
                )
            history.append(now)
            _client_request_times[client_id] = history

            if len(_client_request_times) > _MAX_CLIENT_ENTRIES:
                expired = [k for k, v in _client_request_times.items() if not v or v[-1] <= cutoff]
                for k in expired:
                    _client_request_times.pop(k, None)

    # 3. Request body size limit
    max_bytes = int(os.getenv("CHARGEBACK_MAX_BODY_BYTES", "65536"))
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Payload Too Large"},
                    headers={"X-Request-ID": req_id},
                )
        except ValueError:
            pass

    body_chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload Too Large"},
                headers={"X-Request-ID": req_id},
            )
        body_chunks.append(chunk)
    request._body = b"".join(body_chunks)

    # 4. Timeout and downstream execution
    timeout_sec = float(os.getenv("CHARGEBACK_REQUEST_TIMEOUT_SECONDS", "5.0"))
    try:
        response = await asyncio.wait_for(call_next(request), timeout=timeout_sec)
    except asyncio.TimeoutError:
        current_request_id.reset(token)
        return JSONResponse(
            status_code=504,
            content={"detail": "Request Timeout"},
            headers={"X-Request-ID": req_id},
        )

    # 5. Security headers
    response.headers["X-Request-ID"] = req_id
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    current_request_id.reset(token)
    return response


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

    if (dt - now).total_seconds() > 300:
        raise ValueError(f"Timestamp cannot be in the future: '{ts_str}'")

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


@app.get("/healthz", summary="Liveness probe")
def healthz():
    return {"status": "ok"}


@app.get("/readyz", summary="Readiness probe")
def readyz():
    checks: dict[str, str] = {}
    is_ready = True
    effective_db = os.getenv("CHARGEBACK_DB_PATH") or os.getenv("CHARGEBACK_AUDIT_DB_PATH") or DB_PATH

    # 1. Database check
    try:
        conn = _get_connection(effective_db)
        conn.execute("SELECT 1")
        conn.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        is_ready = False

    # 2. Model check
    try:
        load_or_fit_ml_scorer()
        checks["model"] = "ok"
    except Exception as e:
        checks["model"] = f"error: {e}"
        is_ready = False

    status_code = 200 if is_ready else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
    )


@app.get("/health", summary="Backward-compatible health status")
def health():
    settings = get_settings()
    env = settings.env.lower().strip()
    allow_unverified = (
        env in ("development", "demo")
        and os.getenv("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "0").lower().strip() in ("1", "true")
    )
    keys = settings.get_parsed_api_keys()
    auth_mode = "api-key" if keys else ("demo-open" if env in ("development", "demo") else "unconfigured")
    return {
        "status": "ok",
        "auth": auth_mode,
        "environment": env,
        "allow_unverified_evidence": allow_unverified,
    }


@app.get("/metrics", summary="Prometheus metrics exposition")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _score(
    request: DisputeRequest,
    request_id: str | None = None,
    actor: str = "anonymous",
) -> DecisionResponse:
    if request.reason_code not in REASON_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown reason_code '{request.reason_code}'. Must be one of {REASON_CODES}.",
        )
    dispute = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    dispute["request_id"] = request_id or dispute["dispute_id"]
    dispute["actor"] = actor

    start_time = time.perf_counter()
    decision_dict = decide_case(dispute, actor=actor)
    elapsed = time.perf_counter() - start_time

    resp = DecisionResponse(**decision_dict)

    # Track Prometheus metrics
    DECISIONS_TOTAL.labels(action=resp.action, reason_code=resp.reason_code).inc()
    DECISION_DURATION_SECONDS.labels(action=resp.action).observe(elapsed)
    score_val = resp.evidence_score.get("score") if isinstance(resp.evidence_score, dict) else None
    if score_val is not None:
        EVIDENCE_SCORES.labels(reason_code=resp.reason_code).observe(float(score_val))
    AUDIT_WRITES_TOTAL.labels(status="replayed" if resp.replayed else "success").inc()

    return resp


@app.post("/decision", response_model=DecisionResponse)
def decision(
    request: DisputeRequest,
    x_request_id: str | None = Header(default=None),
    key_info: KeyInfo = Depends(require_decision_scope),
) -> DecisionResponse:
    """Primary decision endpoint with actor-audited policy execution."""
    return _score(request, x_request_id, actor=key_info.key_id)


@app.post("/score", response_model=DecisionResponse, include_in_schema=False)
def score_compatibility(
    request: DisputeRequest,
    x_request_id: str | None = Header(default=None),
    key_info: KeyInfo = Depends(require_decision_scope),
) -> DecisionResponse:
    """Compatibility alias for older callers."""
    return _score(request, x_request_id, actor=key_info.key_id)


@app.get("/audit/verify")
def audit_verify(key_info: KeyInfo = Depends(require_api_key)):
    """Verify the durable SQLite audit hash chain (accessible with decision or read-only key)."""
    effective_db = os.getenv("CHARGEBACK_DB_PATH") or os.getenv("CHARGEBACK_AUDIT_DB_PATH") or DB_PATH
    return verify_audit_integrity(effective_db)
