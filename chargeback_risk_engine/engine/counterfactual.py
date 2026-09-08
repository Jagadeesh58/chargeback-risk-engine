"""Bounded, read-only counterfactual decision analysis."""
from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Callable

from chargeback_risk_engine.config import RELEVANT_EVIDENCE_BY_REASON


def _candidate_inputs(dispute: dict, limit: int = 10):
    fields = RELEVANT_EVIDENCE_BY_REASON[dispute["reason_code"]]
    candidates: list[tuple[str, object, object]] = []
    for field in fields:
        value = dispute.get(field)
        if isinstance(value, bool):
            candidates.append((field, value, not value))
        elif value is None:
            candidates.append((field, None, True))
            if len(candidates) < limit:
                candidates.append((field, None, False))
        if len(candidates) >= limit:
            break
    return candidates[:limit]


def find_minimal_decision_reversal(
    dispute: dict,
    current_result: dict,
    decision_fn: Callable[..., dict],
    *,
    risk_graph=None,
    limit: int = 10,
) -> dict:
    """Flip one valid input at a time and rerun the same canonical path."""
    original_action = current_result["action"]
    best_risk_change: dict | None = None

    with TemporaryDirectory(prefix="chargeback_cf_") as tmp:
        db_path = str(Path(tmp) / "counterfactual.db")
        for field, old_value, new_value in _candidate_inputs(dispute, limit=limit):
            candidate = dict(dispute)
            candidate[field] = new_value
            result = decision_fn(
                candidate,
                risk_graph=risk_graph,
                db_path=db_path,
                include_counterfactual=False,
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
                    "risk_change": float(result["win_probability"]) - float(current_result["win_probability"]),
                    "statement": f"Decision changes from {original_action} to {result['action']} when {field} changes from {old_value!r} to {new_value!r}.",
                }
            if delta > 0 and (best_risk_change is None or delta < best_risk_change["risk_delta_abs"]):
                best_risk_change = {
                    "field": field,
                    "from_value": old_value,
                    "to_value": new_value,
                    "risk_delta_abs": delta,
                }

    if best_risk_change is None:
        return {
            "status": "NO_CHANGE_FOUND",
            "from_action": original_action,
            "statement": "No valid single-input change altered the risk estimate or final decision within the bounded search.",
        }
    return {
        "status": "RISK_CHANGED_DECISION_UNCHANGED",
        "from_action": original_action,
        "changed_field": best_risk_change["field"],
        "from_value": best_risk_change["from_value"],
        "to_value": best_risk_change["to_value"],
        "risk_delta_abs": best_risk_change["risk_delta_abs"],
        "statement": "Risk changed, decision unchanged.",
    }
