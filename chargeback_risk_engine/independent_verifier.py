"""Independent release verifier for the final decision boundary.

This module intentionally does not call the LLM or the production orchestrator.
It checks the persisted decision shape and re-evaluates the hard financial
invariants from the canonical policy inputs.
"""
from __future__ import annotations

import math

from chargeback_risk_engine.policy import AUTO_CONTEST, HUMAN_REVIEW, ACCEPT_LOSS

VALID_ACTIONS = {AUTO_CONTEST, HUMAN_REVIEW, ACCEPT_LOSS}


def verify_decision(result: dict) -> dict:
    errors: list[str] = []
    for field in ("dispute_id", "action", "win_probability", "routing_score", "amount", "economic_decision", "evidence_score", "graph_analysis"):
        if field not in result:
            errors.append(f"missing:{field}")
    if errors:
        return {"valid": False, "errors": errors}

    action = result["action"]
    p = float(result["win_probability"])
    score = float(result["routing_score"])
    amount = float(result["amount"])
    economic = result["economic_decision"]
    evidence = result["evidence_score"]
    graph = result["graph_analysis"]

    if action not in VALID_ACTIONS:
        errors.append("invalid_action")
    if not math.isfinite(p) or not 0 <= p <= 1:
        errors.append("invalid_probability")
    if not math.isfinite(score) or not 0 <= score <= 1:
        errors.append("invalid_routing_score")
    if not math.isfinite(amount) or amount <= 0:
        errors.append("invalid_amount")
    if action == AUTO_CONTEST:
        if amount > 50_000:
            errors.append("ceiling_bypass")
        if float(evidence.get("completeness", 0.0)) < 0.50:
            errors.append("incomplete_evidence_auto_contest")
        if float(evidence.get("validity", 0.0)) < 1.0:
            errors.append("invalid_evidence_auto_contest")
        if float(graph.get("risk_score", 0.0)) >= 0.60:
            errors.append("graph_escalation_bypass")
        if float(economic.get("expected_net_value", -1.0)) <= 0:
            errors.append("negative_economics_auto_contest")

    return {"valid": not errors, "errors": errors, "checked": ["schema", "probability_bounds", "financial_ceiling", "evidence_gate", "graph_gate", "positive_economics"]}
