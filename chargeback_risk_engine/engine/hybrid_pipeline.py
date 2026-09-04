"""AI + evidence + economics + deterministic policy orchestration."""
from __future__ import annotations

import pandas as pd

from chargeback_risk_engine.audit_log import (
    DB_PATH,
    get_existing_decision,
    get_or_create_decision,
    load_graph_rows,
)
from chargeback_risk_engine.calibration import apply_calibration, load_or_fit_calibration_points
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import dispute_from_evidence_items, load_or_fit_ml_scorer
from training.train_models import load_or_fit_tree_model, predict_model
from chargeback_risk_engine.policy import decide
from chargeback_risk_engine.razorpay_adapter import generate_contest_draft
from chargeback_risk_engine.scorer import predict_win_probability
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.engine.explainability import build_explanation, logistic_feature_contributions
from chargeback_risk_engine.engine.risk_graph import ENTITY_FIELDS, RiskGraph
from chargeback_risk_engine.engine.risk_model import combine_probabilities
from chargeback_risk_engine.config import (
    MODEL_VERSION,
    LOGISTIC_MODEL_VERSION,
    TREE_MODEL_VERSION,
    FEATURE_VERSION,
    POLICY_VERSION,
)

RULES_MODEL_VERSION = "rules-v1"


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


def score_hybrid(dispute: dict, *, risk_graph: RiskGraph | None = None, db_path: str = DB_PATH) -> dict:
    # Check idempotency before loading model artifacts. Replays should use only
    # the original durable decision context, never values from a mutated retry.
    existing = get_existing_decision(dispute["dispute_id"], db_path)

    ml = load_or_fit_ml_scorer()
    tree_model, tree_columns = load_or_fit_tree_model()
    points = load_or_fit_calibration_points()

    def compute():
        packet = assemble(dispute)
        evidence_quality = score_evidence(dispute, packet)
        rule_probability = predict_win_probability(dispute)
        ml_dispute = dispute_from_evidence_items(
            dispute["reason_code"],
            [{"field": item.field, "status": item.status} for item in packet.items],
        )
        logistic_probability = ml.predict_win_probability(ml_dispute)
        tree_probability = float(
            predict_model(tree_model, tree_columns, pd.DataFrame([dispute]))[0]
        )
        hybrid_probability = combine_probabilities(
            rules=rule_probability,
            logistic=logistic_probability,
            tree=tree_probability,
        )
        graph_result = graph.analyze(dispute)
        economic = calculate_economic_value(dispute["amount"], hybrid_probability)
        confidence = min(1.0, 0.5 + abs(hybrid_probability - 0.5))
        decision = decide(
            hybrid_probability,
            dispute["amount"],
            evidence_packet=packet,
            model_confidence=confidence,
            expected_net_value=economic.expected_net_value,
            evidence_quality=evidence_quality,
            graph_risk_score=graph_result.risk_score,
        )
        evidence_list = [
            {"field": item.field, "status": item.status} for item in packet.items
        ]
        return (
            hybrid_probability,
            evidence_list,
            decision.action,
            decision.reason,
            decision.expected_value,
            _graph_data_for(dispute),
        )

    if existing is None:
        # The current request is analyzed against all previously logged disputes.
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
        )
    else:
        logged = existing

    # Always rebuild the response from the durable original record. This makes
    # every response field deterministic across replayed/mutated requests.
    original_dispute = _logged_dispute(logged)
    graph = RiskGraph(load_graph_rows(db_path)) if risk_graph is None else risk_graph
    if logged.dispute_id not in {
        node_id.split(":", 1)[1]
        for node_id in graph.node_to_entities
    }:
        graph.add(original_dispute)

    calibrated_probability = apply_calibration(points, logged.win_probability)
    ml_dispute = dispute_from_evidence_items(logged.reason_code, logged.evidence)
    logistic_probability = ml.predict_win_probability(ml_dispute)

    tree_probability = float(
        predict_model(tree_model, tree_columns, pd.DataFrame([original_dispute]))[0]
    )
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
    draft = None
    if logged.action == "AUTO-CONTEST":
        draft = generate_contest_draft(
            logged.dispute_id, logged.amount, logged.evidence, logged.reason
        )

    return {
        "dispute_id": logged.dispute_id,
        "win_probability": logged.win_probability,
        "calibrated_win_probability": calibrated_probability,
        # IMPORTANT: derive this from the logged original dispute, never the
        # current retry payload, so idempotent replays cannot drift.
        "rule_win_probability": predict_win_probability(original_dispute),
        "ml_win_probability": logistic_probability,
        "tree_model_probability": tree_probability,
        "evidence": logged.evidence,
        "evidence_score": evidence_quality.to_dict(),
        "graph_analysis": graph_result.to_dict(),
        "economic_decision": economic.to_dict(),
        "action": logged.action,
        "reason": logged.reason,
        "expected_value": logged.expected_value,
        "replayed": logged.replayed,
        "contest_draft": draft,
        "explanation": explanation,
        "model_version": MODEL_VERSION,
        "rule_model_version": RULES_MODEL_VERSION,
        "logistic_model_version": LOGISTIC_MODEL_VERSION,
        "tree_model_version": TREE_MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "policy_version": POLICY_VERSION,
    }
