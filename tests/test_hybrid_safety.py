from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.policy import decide
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.engine.risk_graph import RiskGraph
from chargeback_risk_engine.engine.risk_model import combine_probabilities
from chargeback_risk_engine.engine.explainability import logistic_feature_contributions
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer


def test_hybrid_probability_stays_bounded():
    p = combine_probabilities(rules=0.1, logistic=0.8, tree=0.9)
    assert 0.0 <= p <= 1.0


def test_invalid_or_contradictory_evidence_cannot_auto_contest():
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": False,
        "has_signature_confirmation": True,
        "has_delivery_confirmation_consistent": False,
    }
    packet = assemble(dispute)
    quality = score_evidence(dispute, packet)
    decision = decide(0.99, 1000, evidence_packet=packet, evidence_quality=quality, expected_net_value=1000)
    assert decision.action == "HUMAN REVIEW"


def test_high_graph_risk_forces_human_review():
    decision = decide(0.99, 1000, evidence_packet=None, expected_net_value=1000, graph_risk_score=0.9)
    assert decision.action == "HUMAN REVIEW"


def test_logistic_contributions_are_deterministic():
    scorer = load_or_fit_ml_scorer()
    dispute = {"reason_code": "item_not_received", "has_tracking_number": True, "has_delivery_confirmation": True, "has_signature_confirmation": None}
    first = logistic_feature_contributions(scorer, dispute)
    second = logistic_feature_contributions(scorer, dispute)
    assert first == second
    assert first


def test_graph_reports_abuse_type_for_large_shared_cluster():
    rows = []
    for i in range(8):
        rows.append({"dispute_id": f"d{i}", "customer_id": f"c{i}", "device_id": "shared-dev", "ip_address": "shared-ip", "amount": 1000})
    graph = RiskGraph(rows)
    result = graph.analyze(rows[0])
    assert result.risk_type == "ORGANIZED_ABUSE"
    assert result.connected_accounts >= 8


def test_missing_evidence_forces_human_review_even_when_probability_is_low():
    dispute = {"reason_code": "item_not_received", "has_tracking_number": None, "has_delivery_confirmation": None, "has_signature_confirmation": None}
    packet = assemble(dispute)
    quality = score_evidence(dispute, packet)
    decision = decide(0.05, 500, evidence_packet=packet, evidence_quality=quality, expected_net_value=-100)
    assert decision.action == "HUMAN REVIEW"
