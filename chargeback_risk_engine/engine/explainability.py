"""Structured, deterministic decision explanations."""
from __future__ import annotations


def build_explanation(
    *,
    risk_probability: float,
    evidence_score: dict,
    economic: dict,
    policy_reason: str,
    final_action: str,
    graph_analysis: dict | None = None,
    feature_importance: dict[str, float] | None = None,
) -> dict:
    items = evidence_score.get("items", [])
    supporting = [i["field"] for i in items if i.get("status") == "PASS"]
    missing = [i["field"] for i in items if i.get("status") != "PASS"]
    importance = feature_importance or {}
    top = sorted(importance.items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
    top_risk_factors = [f"{name} ({value:+.3f})" for name, value in top if value > 0]
    return {
        "risk_probability": float(risk_probability),
        "top_risk_factors": top_risk_factors,
        "supporting_evidence": supporting,
        "missing_evidence": missing,
        "economic_reason": (
            f"Expected recovery ₹{economic['expected_recovery']:,.2f} vs expected contest costs "
            f"₹{economic['expected_cost']:,.2f}; expected net value ₹{economic['expected_net_value']:,.2f}."
        ),
        "policy_reason": policy_reason,
        "safety_notes": [
            "Model output is advisory.",
            "Missing evidence is not treated as positive evidence.",
            "Final action is selected by deterministic policy.",
        ],
        "graph_reason": graph_analysis.get("explanation") if graph_analysis else "Graph analysis not available.",
        "final_action": final_action,
    }


def logistic_feature_contributions(ml_scorer, dispute: dict) -> dict[str, float]:
    """Deterministic per-feature contributions for the reason-code LogisticRegression.

    Contribution is coefficient * encoded feature value. This is an equivalent
    local explanation for the linear model and is reproducible without SHAP.
    """
    reason = dispute["reason_code"]
    model = ml_scorer.models[reason]
    from chargeback_risk_engine.config import RELEVANT_EVIDENCE_BY_REASON
    fields = RELEVANT_EVIDENCE_BY_REASON[reason]
    encoded = [1.0 if dispute.get(f) is True else 0.0 if dispute.get(f) is False else 0.5 for f in fields]
    return {field: float(coef * value) for field, coef, value in zip(fields, model.coef_[0], encoded)}


def permutation_feature_importance(model, X, y, feature_names, random_state: int = 42) -> dict[str, float]:
    """Deterministic model-agnostic feature importance for tabular models."""
    from sklearn.inspection import permutation_importance
    result = permutation_importance(model, X, y, n_repeats=8, random_state=random_state, scoring="roc_auc")
    return {name: float(value) for name, value in zip(feature_names, result.importances_mean)}
