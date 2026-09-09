"""Optional Track 01-style proposal gate: proposal, not LLM authority."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class CommerceProposal:
    amount: float
    currency: str
    merchant_id: str
    user_consented: bool
    idempotency_key: str


def gate(proposal: CommerceProposal, *, max_amount: float = 10_000.0, seen_keys: set[str] | None = None) -> tuple[bool, str]:
    if proposal.amount <= 0 or proposal.amount > max_amount:
        return False, "amount_outside_bound"
    if proposal.currency != "INR":
        return False, "currency_not_allowed"
    if not proposal.user_consented:
        return False, "missing_user_consent"
    if seen_keys is not None and proposal.idempotency_key in seen_keys:
        return False, "replay_detected"
    return True, "approved_for_deterministic_executor"
