"""
evidence.py — assembles a reason-code-aware evidence packet with honest
PASS/WARN/FAIL status per field (principle #10). Never fabricates
evidence: an unknown field is WARN, never silently treated as present.
"""

from dataclasses import dataclass

from config import RELEVANT_EVIDENCE_BY_REASON


@dataclass
class EvidenceItem:
    field: str
    status: str  # "PASS" | "WARN" | "FAIL"


@dataclass
class EvidencePacket:
    reason_code: str
    items: list[EvidenceItem]

    @property
    def pass_count(self) -> int:
        return sum(1 for i in self.items if i.status == "PASS")

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.items if i.status == "WARN")

    @property
    def fail_count(self) -> int:
        return sum(1 for i in self.items if i.status == "FAIL")

    @property
    def total(self) -> int:
        return len(self.items)


def assemble(dispute: dict) -> EvidencePacket:
    """
    True  -> PASS (present and relevant, confirmed)
    False -> FAIL (required and confirmed missing)
    None  -> WARN (present but incomplete -- unknown, never fabricated as PASS)
    """
    reason_code = dispute["reason_code"]
    relevant_fields = RELEVANT_EVIDENCE_BY_REASON[reason_code]

    items = []
    for field_name in relevant_fields:
        value = dispute.get(field_name)
        if value is True:
            status = "PASS"
        elif value is False:
            status = "FAIL"
        else:
            status = "WARN"
        items.append(EvidenceItem(field=field_name, status=status))

    return EvidencePacket(reason_code=reason_code, items=items)