from extensions.agentic_commerce_gate import CommerceProposal, gate
from extensions.revenue_recovery import choose_plan
from extensions.finance_reconciliation import match_one


def test_commerce_gate_requires_consent_and_bounds():
    p = CommerceProposal(100, "INR", "m1", False, "k1")
    assert gate(p)[0] is False
    p = CommerceProposal(100, "INR", "m1", True, "k1")
    assert gate(p)[0] is True
    assert gate(p, seen_keys={"k1"})[0] is False


def test_recovery_has_no_action_when_value_negative():
    assert choose_plan(100, 0.01).intervention == "NO_ACTION"
    assert choose_plan(1000, 0.9).max_attempts == 1


def test_reconciliation_reference_match():
    c = {"id": "c1", "amount": 100, "currency": "INR", "reference": "R1", "payer": "A"}
    i = {"id": "i1", "amount": 100, "currency": "INR", "reference": "R1", "customer": "A"}
    assert match_one(c, i).confidence == 0.99
