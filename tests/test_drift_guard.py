from chargeback_risk_engine.monitoring.drift_guard import detect_drift


def test_normal_drift_report():
    r = detect_drift({"x": [1, 1, 1]}, {"x": [1.01, 1, 0.99]})
    assert r.status == "NORMAL"
    assert r.adaptation_action == "CONTINUE_MONITORING"


def test_material_shift_never_auto_retrains():
    r = detect_drift({"x": [0, 0, 0, 0]}, {"x": [10, 10, 10, 10]})
    assert r.status == "ADAPTATION_CANDIDATE"
    assert r.adaptation_action == "HUMAN_REVIEW_AND_RECALIBRATION"
    assert "promotion" in r.reason
