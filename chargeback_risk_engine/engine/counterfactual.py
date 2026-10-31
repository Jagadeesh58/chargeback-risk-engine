"""Bounded, read-only counterfactual decision analysis."""

from __future__ import annotations

import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from chargeback_risk_engine.config import RELEVANT_EVIDENCE_BY_REASON
from chargeback_risk_engine.policy import GRAPH_HUMAN_REVIEW_THRESHOLD


def _candidate_inputs(dispute: dict, limit: int = 10):
    fields = RELEVANT_EVIDENCE_BY_REASON[dispute["reason_code"]]
    candidates: list[tuple[str, object, object]] = []
    for field in fields:
        value = dispute.get(field)
        # Restrict candidate flips to merchant-obtainable fields:
        # Flipping a boolean that is already True to False is never an actionable suggestion.
        # Only flip None or False -> True.
        if value is False or value is None:
            candidates.append((field, value, True))
        if len(candidates) >= limit:
            break
    return candidates[:limit]


# Counterfactual cases are read-only simulations.
# Candidate disputes must never be persisted or treated as real disputes.


def find_single_change_decision_reversal(
    dispute: dict,
    current_result: dict,
    decision_fn: Callable[..., dict],
    *,
    risk_graph=None,
    limit: int = 10,
) -> dict:
    """Single-change counterfactual decision reversal analysis.

    Evaluates whether flipping a single unconfirmed or missing evidence field (None/False -> True)
    reverses the deterministic policy decision. Operates on an isolated copy of the risk graph
    so candidate simulations never mutate shared caller state. Note: this examines single-change
    reversals and does not guarantee joint-flip optimality.
    """
    original_action = current_result["action"]
    best_risk_change: dict | None = None
    graph_risk = float(current_result.get("graph_analysis", {}).get("risk_score", 0.0))
    is_graph_escalated = graph_risk >= GRAPH_HUMAN_REVIEW_THRESHOLD

    base_graph = (
        risk_graph.clone()
        if hasattr(risk_graph, "clone")
        else copy.deepcopy(risk_graph)
        if risk_graph is not None
        else None
    )

    with TemporaryDirectory(prefix="chargeback_cf_") as tmp:
        db_path = str(Path(tmp) / "counterfactual.db")
        for field, old_value, new_value in _candidate_inputs(dispute, limit=limit):
            candidate = dict(dispute)
            candidate["dispute_id"] = (
                f"CF_{dispute.get('dispute_id', 'CASE')}_{field}_{new_value!r}"[:120]
            )
            candidate[field] = new_value
            candidate_graph = (
                base_graph.clone()
                if (base_graph is not None and hasattr(base_graph, "clone"))
                else copy.deepcopy(base_graph)
                if base_graph is not None
                else None
            )
            result = decision_fn(
                candidate,
                risk_graph=candidate_graph,
                db_path=db_path,
                include_counterfactual=False,
                call_ai_analyst=False,
            )
            delta = abs(float(result["win_probability"]) - float(current_result["win_probability"]))
            if result["action"] != original_action:
                return {
                    "status": "DECISION_CHANGED",
                    "from_action": original_action,
                    "to_action": result["action"],
                    "changed_field": field,
                    "from_value": old_value,
                    "to_value": new_value,
                    "risk_change": float(result["win_probability"])
                    - float(current_result["win_probability"]),
                    "statement": f"Decision changes from {original_action} to {result['action']} when {field} changes from {old_value!r} to {new_value!r}.",
                }
            if delta > 0 and (
                best_risk_change is None or delta < best_risk_change["risk_delta_abs"]
            ):
                best_risk_change = {
                    "field": field,
                    "from_value": old_value,
                    "to_value": new_value,
                    "risk_delta_abs": delta,
                }

    if is_graph_escalated:
        stmt = "No valid single-evidence change altered the decision; the case is held for manual review by relationship-risk cluster escalation."
    elif best_risk_change is None:
        stmt = "No valid single-input change altered the risk estimate or final decision within the bounded search."
    else:
        stmt = f"Changing {best_risk_change['field']} from {best_risk_change['from_value']!r} to {best_risk_change['to_value']!r} changes the modeled risk, but the deterministic policy still returns {original_action}."

    if best_risk_change is None:
        return {
            "status": "NO_CHANGE_FOUND",
            "from_action": original_action,
            "statement": stmt,
        }
    return {
        "status": "RISK_CHANGED_DECISION_UNCHANGED",
        "from_action": original_action,
        "changed_field": best_risk_change["field"],
        "from_value": best_risk_change["from_value"],
        "to_value": best_risk_change["to_value"],
        "risk_delta_abs": best_risk_change["risk_delta_abs"],
        "statement": stmt,
    }


find_minimal_decision_reversal = find_single_change_decision_reversal
