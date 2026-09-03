"""Evidence intelligence: quality, completeness, validity and provenance-aware scoring.

The existing evidence.py remains the canonical PASS/WARN/FAIL gate. This module
adds richer metadata without changing that gate's semantics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from chargeback_risk_engine.config import RELEVANT_EVIDENCE_BY_REASON


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
    reason = dispute["reason_code"]
    fields = RELEVANT_EVIDENCE_BY_REASON[reason]
    packet_by_field = {i.field: i for i in evidence_packet.items} if evidence_packet else {}
    items: list[EvidenceIntelligenceItem] = []
    for field in fields:
        value = dispute.get(field)
        available = value is not None
        valid = isinstance(value, bool) or value is None
        status = packet_by_field.get(field).status if field in packet_by_field else ("PASS" if value is True else "FAIL" if value is False else "WARN")
        # Missing evidence is deliberately low-confidence, never positive evidence.
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
                status=status,
            )
        )
    n = len(items) or 1
    completeness = sum(i.available for i in items) / n
    validity = sum(i.valid and i.consistent for i in items) / n
    confidence = sum(i.confidence for i in items) / n
    return EvidenceScore(reason_code=reason, completeness=completeness, validity=validity, confidence=confidence, items=tuple(items))
