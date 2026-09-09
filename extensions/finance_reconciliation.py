"""Optional Track 04-style deterministic reconciliation primitive."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Match:
    credit_id: str
    invoice_id: str
    confidence: float


def match_one(credit: dict, invoice: dict, *, amount_tolerance: float = 0.01) -> Match | None:
    if credit.get("currency") != invoice.get("currency"):
        return None
    if abs(float(credit.get("amount", 0)) - float(invoice.get("amount", 0))) > amount_tolerance:
        return None
    if credit.get("reference") and invoice.get("reference") == credit.get("reference"):
        return Match(str(credit["id"]), str(invoice["id"]), 0.99)
    payer = str(credit.get("payer", "")).strip().lower()
    customer = str(invoice.get("customer", "")).strip().lower()
    if payer and customer and payer == customer:
        return Match(str(credit["id"]), str(invoice["id"]), 0.90)
    return None
