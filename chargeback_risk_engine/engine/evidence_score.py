"""Deterministic evidence quality metadata built from the canonical evidence packet."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from chargeback_risk_engine.config import RELEVANT_EVIDENCE_BY_REASON
from chargeback_risk_engine.evidence import assemble


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

    meta_dict = dispute.get("evidence_meta") if isinstance(dispute.get("evidence_meta"), dict) else {}
    has_any_provenance = any(
        (k.endswith("_source") or k.endswith("_timestamp") or k == "evidence_timestamp")
        and dispute.get(k) is not None
        for k in dispute.keys()
    ) or bool(meta_dict)

    for field in RELEVANT_EVIDENCE_BY_REASON[reason]:
        value = dispute.get(field)
        item = packet_by_field[field]
        available = isinstance(value, bool)
        valid = isinstance(value, bool) or value is None
        confidence = 0.95 if value is True and valid else 0.80 if value is False and valid else 0.25

        field_meta = meta_dict.get(field) if isinstance(meta_dict, dict) else None
        if hasattr(field_meta, "model_dump"):
            field_meta = field_meta.model_dump()
        elif hasattr(field_meta, "dict"):
            field_meta = field_meta.dict()
        elif not isinstance(field_meta, dict):
            field_meta = {}

        field_source = dispute.get(f"{field}_source") or field_meta.get("source")
        field_ts = dispute.get(f"{field}_timestamp") or field_meta.get("timestamp") or dispute.get("evidence_timestamp")
        field_consistent = dispute.get(f"{field}_consistent")
        if field_consistent is None:
            field_consistent = field_meta.get("consistent", True)

        source_str = str(field_source or "merchant_record")

        # Provenance verification rule:
        # Any True evidence value whose source is "manual_upload" or "unknown"
        # or whose timestamp is missing counts as UNVERIFIED (treated as WARN for auto-contest gate).
        is_verified = True
        if value is True:
            if field_source in ("manual_upload", "unknown") or source_str in ("manual_upload", "unknown"):
                is_verified = False
            elif has_any_provenance and (not field_ts or not field_source):
                is_verified = False

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
    source_reliability = dispute.get("evidence_source_reliability")
    try:
        source_reliability = float(source_reliability)
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
