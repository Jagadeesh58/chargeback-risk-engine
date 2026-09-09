"""AI + evidence + economics + deterministic policy orchestration."""
from __future__ import annotations


from chargeback_risk_engine.audit_log import (
    DB_PATH,
    get_existing_decision,
    get_or_create_decision,
    load_graph_rows,
)
from chargeback_risk_engine.calibration import apply_calibration, load_or_fit_calibration_points
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import dispute_from_evidence_items, load_or_fit_ml_scorer
from chargeback_risk_engine.policy import decide
from chargeback_risk_engine.razorpay_adapter import generate_contest_draft
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.ai_analyst import analyze_evidence
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.engine.decision_result import CanonicalDecision
from chargeback_risk_engine.engine.explainability import build_explanation, logistic_feature_contributions
from chargeback_risk_engine.engine.risk_graph import ENTITY_FIELDS, RiskGraph
from chargeback_risk_engine.engine.risk_model import live_risk_probability
from chargeback_risk_engine.config import (
    MODEL_VERSION,
    FEATURE_VERSION,
    POLICY_VERSION,
    CHALLENGER_MODEL_VERSION,
    RULE_MODEL_VERSION,
)


def _logged_dispute(logged) -> dict:
    """Reconstruct the original scored dispute from its durable audit record."""
    dispute = {
        "dispute_id": logged.dispute_id,
        "reason_code": logged.reason_code,
        "amount": logged.amount,
    }
    dispute.update(logged.graph_data or {})
    status_to_value = {"PASS": True, "FAIL": False, "WARN": None}
    for item in logged.evidence:
        dispute[item["field"]] = status_to_value[item["status"]]
    return dispute


def _graph_data_for(dispute: dict) -> dict:
    """Persist only the relationship identifiers needed to rebuild graph history."""
    return {
        field: dispute[field]
        for field in ENTITY_FIELDS
        if dispute.get(field) not in (None, "")
    }


def _score_case(
    dispute: dict,
    *,
    risk_graph: RiskGraph | None = None,
    db_path: str = DB_PATH,
) -> dict:
    """Score and persist one case through the canonical decision path."""
    existing = get_existing_decision(dispute["dispute_id"], db_path)
    ml = load_or_fit_ml_scorer()
    points = load_or_fit_calibration_points()

    def compute():
        packet = assemble(dispute)
        evidence_quality = score_evidence(dispute, packet)
        risk_probability = live_risk_probability(ml, dispute)
        graph_result = graph.analyze(dispute)
        economic = calculate_economic_value(dispute["amount"], risk_probability)
        decision = decide(
            risk_probability,
            dispute["amount"],
            evidence_packet=packet,
            expected_net_value=economic.expected_net_value,
            evidence_quality=evidence_quality,
            graph_risk_score=graph_result.risk_score,
        )
        evidence_list = [{"field": item.field, "status": item.status} for item in packet.items]
        ai_analysis = analyze_evidence({"reason_code": packet.reason_code, "items": evidence_list}, reason_code=packet.reason_code, context_text=str(dispute.get("evidence_text", "")))
        return (
            risk_probability,
            evidence_list,
            decision.action,
            decision.reason,
            decision.expected_value,
            _graph_data_for(dispute),
            ai_analysis.to_dict(),
        )

    if existing is None:
        graph = risk_graph or RiskGraph(load_graph_rows(db_path))
        logged = get_or_create_decision(
            dispute_id=dispute["dispute_id"],
            reason_code=dispute["reason_code"],
            amount=dispute["amount"],
            compute_decision_fn=compute,
            db_path=db_path,
            model_version=MODEL_VERSION,
            feature_version=FEATURE_VERSION,
            policy_version=POLICY_VERSION,
            ai_metadata=None,
            request_id=str(dispute.get("request_id", dispute["dispute_id"])),
        )
    else:
        logged = existing

    original_dispute = _logged_dispute(logged)
    graph = RiskGraph(load_graph_rows(db_path)) if risk_graph is None else risk_graph
    known_ids = {
        node_id.split(":", 1)[1]
        for node_id in graph.node_to_entities
        if ":" in node_id
    }
    if logged.dispute_id not in known_ids:
        graph.add(original_dispute)

    calibrated_probability = apply_calibration(points, logged.win_probability)
    ml_dispute = dispute_from_evidence_items(logged.reason_code, logged.evidence)
    evidence_packet = assemble(original_dispute)
    evidence_quality = score_evidence(original_dispute, evidence_packet)
    graph_result = graph.analyze(original_dispute)
    economic = calculate_economic_value(logged.amount, logged.win_probability)
    contributions = logistic_feature_contributions(ml, ml_dispute)
    explanation = build_explanation(
        risk_probability=logged.win_probability,
        evidence_score=evidence_quality.to_dict(),
        economic=economic.to_dict(),
        policy_reason=logged.reason,
        final_action=logged.action,
        graph_analysis=graph_result.to_dict(),
        feature_importance=contributions,
    )
    ai_analysis = logged.ai_metadata or analyze_evidence({"reason_code": logged.reason_code, "items": logged.evidence}, reason_code=logged.reason_code).to_dict()
    draft = None
    if logged.action == "AUTO-CONTEST":
        draft = generate_contest_draft(
            logged.dispute_id, logged.amount, logged.evidence, logged.reason
        )

    return {
        "dispute_id": logged.dispute_id,
        "reason_code": logged.reason_code,
        "amount": logged.amount,
        "win_probability": logged.win_probability,
        "calibrated_win_probability": calibrated_probability,
        "evidence": logged.evidence,
        "evidence_score": evidence_quality.to_dict(),
        "graph_analysis": graph_result.to_dict(),
        "economic_decision": economic.to_dict(),
        "action": logged.action,
        "reason": logged.reason,
        "expected_value": logged.expected_value,
        "replayed": logged.replayed,
        "contest_draft": draft,
        "explanation": {**explanation, "ai_analyst": ai_analysis},
        "counterfactual": {"status": "PENDING"},
        "audit_id": f"decision:{logged.dispute_id}",
        "request_id": logged.request_id,
        "model_version": MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "feature_version": FEATURE_VERSION,
        "live_model": MODEL_VERSION,
        "challenger_models": {
            "rules": RULE_MODEL_VERSION,
            "hgb": CHALLENGER_MODEL_VERSION,
        },
    }


def decide_case(
    dispute: dict,
    *,
    risk_graph: RiskGraph | None = None,
    db_path: str = DB_PATH,
    include_counterfactual: bool = True,
) -> dict:
    """Public canonical entry point used by API, UI, demo and evaluation."""
    result = _score_case(dispute, risk_graph=risk_graph, db_path=db_path)
    if include_counterfactual:
        from chargeback_risk_engine.engine.counterfactual import find_minimal_decision_reversal
        original_record = get_existing_decision(dispute["dispute_id"], db_path)
        counterfactual_input = _logged_dispute(original_record) if original_record is not None else dict(dispute)
        result["counterfactual"] = find_minimal_decision_reversal(
            counterfactual_input,
            result,
            decide_case,
            risk_graph=risk_graph,
        )
        result["explanation"]["what_would_change"] = result["counterfactual"]["statement"]
    result_obj = CanonicalDecision(**result)
    return result_obj.to_dict()
