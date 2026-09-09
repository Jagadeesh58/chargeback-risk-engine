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

    for field in RELEVANT_EVIDENCE_BY_REASON[reason]:
        value = dispute.get(field)
        item = packet_by_field[field]
        available = isinstance(value, bool)
        valid = isinstance(value, bool) or value is None
        confidence = 0.95 if value is True and valid else 0.80 if value is False and valid else 0.25
        items.append(
            EvidenceIntelligenceItem(
                field=field,
                available=available,
                valid=valid,
                confidence=confidence,
                timestamp=dispute.get(f"{field}_timestamp") or dispute.get("evidence_timestamp"),
                source=str(dispute.get(f"{field}_source") or "merchant_record"),
                consistent=dispute.get(f"{field}_consistent", True) is not False,
                status=item.status,
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
