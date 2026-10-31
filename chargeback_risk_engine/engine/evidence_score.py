"""Deterministic evidence quality metadata built from the canonical evidence packet."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from chargeback_risk_engine.config import RELEVANT_EVIDENCE_BY_REASON
from chargeback_risk_engine.evidence import assemble

TRUSTED_SOURCES = frozenset({"carrier_api", "psp_log", "merchant_record"})


def validate_evidence_timestamp(ts_str: str | None) -> bool:
    """Validate ISO-8601 timestamp against in-window bounds.

    Must not be in the future (> 300s clock skew) and must not be older than
    CHARGEBACK_MAX_EVIDENCE_AGE_DAYS (default 365 days).
    """
    if not ts_str:
        return False
    try:
        clean_ts = str(ts_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Future check with 300s clock skew
    if (dt - now).total_seconds() > 300:
        return False

    try:
        max_age_days = float(os.getenv("CHARGEBACK_MAX_EVIDENCE_AGE_DAYS", "365"))
    except ValueError:
        max_age_days = 365.0

    if (now - dt).total_seconds() > max_age_days * 86400:
        return False

    return True


@dataclass(frozen=True)
class EvidenceIntelligenceItem:
    field: str
    available: bool
    valid: bool
    confidence: float
    timestamp: str | None
    source: str
    consistent: bool
    status: str
    verified: bool = True


@dataclass(frozen=True)
class EvidenceScore:
    reason_code: str
    completeness: float
    validity: float
    confidence: float
    items: tuple[EvidenceIntelligenceItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "completeness": self.completeness,
            "validity": self.validity,
            "confidence": self.confidence,
            "items": [asdict(item) for item in self.items],
        }


def score_evidence(dispute: dict, evidence_packet=None) -> EvidenceScore:
    """Add quality metadata to the canonical PASS/WARN/FAIL packet."""
    reason = dispute["reason_code"]
    packet = evidence_packet or assemble(dispute)
    packet_by_field = {item.field: item for item in packet.items}
    items: list[EvidenceIntelligenceItem] = []

    meta_dict = (
        dispute.get("evidence_meta") if isinstance(dispute.get("evidence_meta"), dict) else {}
    )
    has_any_provenance = any(
        (k.endswith("_source") or k.endswith("_timestamp") or k == "evidence_timestamp")
        and dispute.get(k) is not None
        for k in dispute.keys()
    ) or bool(meta_dict)

    env = os.getenv("CHARGEBACK_ENV", "production").lower().strip()
    allow_unverified = env in ("development", "demo") and os.getenv(
        "CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "0"
    ).lower().strip() in ("1", "true")

    for field in RELEVANT_EVIDENCE_BY_REASON[reason]:
        value = dispute.get(field)
        item = packet_by_field[field]
        available = isinstance(value, bool)
        valid = isinstance(value, bool) or value is None
        confidence = 0.95 if value is True and valid else 0.80 if value is False and valid else 0.25

        field_meta = meta_dict.get(field) if isinstance(meta_dict, dict) else None
        if field_meta is not None and hasattr(field_meta, "model_dump"):
            field_meta = field_meta.model_dump()
        elif field_meta is not None and hasattr(field_meta, "dict"):
            field_meta = field_meta.dict()
        elif not isinstance(field_meta, dict):
            field_meta = {}

        field_source = dispute.get(f"{field}_source") or field_meta.get("source")
        field_ts = (
            dispute.get(f"{field}_timestamp")
            or field_meta.get("timestamp")
            or dispute.get("evidence_timestamp")
        )
        field_consistent = dispute.get(f"{field}_consistent")
        if field_consistent is None:
            field_consistent = field_meta.get("consistent", True)

        source_str = str(
            field_source or ("unspecified" if not allow_unverified else "merchant_record")
        )

        # Provenance verification rule:
        # Evidence value True counts as VERIFIED only if it has an allowed trusted source
        # (carrier_api, psp_log, merchant_record) AND a valid in-window timestamp.
        # In development/demo, CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE=1 relaxes omission only
        # when no provenance is tracked on the request; partial or untrusted provenance is always unverified.
        is_verified = True
        if value is True:
            if allow_unverified and not has_any_provenance:
                is_verified = True
            else:
                has_trusted_source = bool(
                    field_source and str(field_source).lower() in TRUSTED_SOURCES
                )
                valid_ts = validate_evidence_timestamp(field_ts)
                is_verified = has_trusted_source and valid_ts

        items.append(
            EvidenceIntelligenceItem(
                field=field,
                available=available,
                valid=valid,
                confidence=confidence,
                timestamp=field_ts,
                source=source_str,
                consistent=field_consistent is not False,
                status=item.status,
                verified=is_verified,
            )
        )

    n = len(items) or 1
    completeness = sum(item.available for item in items) / n
    validity = sum(item.valid and item.consistent for item in items) / n
    field_confidence = sum(item.confidence for item in items) / n
    source_reliability_val = dispute.get("evidence_source_reliability")
    source_reliability: float | None = None
    if source_reliability_val is not None:
        try:
            source_reliability = float(source_reliability_val)
        except (TypeError, ValueError):
            source_reliability = None
    if source_reliability is not None and 0.0 <= source_reliability <= 1.0:
        confidence = 0.65 * field_confidence + 0.35 * source_reliability
    else:
        confidence = field_confidence
    return EvidenceScore(
        reason_code=reason,
        completeness=completeness,
        validity=validity,
        confidence=confidence,
        items=tuple(items),
    )
