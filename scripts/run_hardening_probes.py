"""Run and report verification probes for system hardening."""

import concurrent.futures
import json
import os
import tempfile

from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app
from chargeback_risk_engine.audit_log import verify_audit_integrity
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.risk_graph import GRAPH_ESCALATION_THRESHOLD, RiskGraph
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer, save_ml_scorer


def run_probe_1():
    print("=== PROBE 1: Concurrent Decisions & Audit Hash Integrity ===")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "probe1_audit.db")

        def make_decision(i: int):
            dispute = {
                "dispute_id": f"CONCUR_{i:03d}",
                "reason_code": "item_not_received",
                "amount": 1000.0 + i,
                "customer_id": f"cust_{i}",
                "has_tracking_number": True,
                "has_delivery_confirmation": True,
                "has_signature_confirmation": True,
            }
            return decide_case(dispute, db_path=db_path, include_counterfactual=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(make_decision, range(24)))

        integrity = verify_audit_integrity(db_path)
        print(f"Total concurrent decisions completed: {len(results)}")
        print(
            f"Audit log integrity check: valid={integrity['valid']}, checked={integrity['checked']}, head_hash={integrity.get('head_hash', '')[:16]}..."
        )
        assert len(results) == 24
        assert integrity["valid"] is True
        assert integrity["checked"] == 24
        print("PROBE 1 RESULT: PASS\n")


def run_probe_2():
    print("=== PROBE 2: Merchant Linkage False-Positive Control ===")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "probe2_audit.db")
        actions = []
        risk_scores = []
        cluster_sizes = []

        for i in range(10):
            dispute = {
                "dispute_id": f"MERCH_CLEAN_{i:02d}",
                "reason_code": "item_not_received",
                "amount": 2000.0,
                "merchant_id": "busy_merchant_xyz",
                "customer_id": f"unrelated_buyer_{i}",
                "card_fingerprint": f"card_tok_{i}",
                "device_id": f"dev_{i}",
                "ip_address": f"198.51.100.{10 + i}",
                "has_tracking_number": True,
                "has_delivery_confirmation": True,
                "has_signature_confirmation": True,
            }
            res = decide_case(dispute, db_path=db_path, include_counterfactual=False)
            actions.append(res["action"])
            risk_scores.append(res["graph_analysis"]["risk_score"])
            cluster_sizes.append(res["graph_analysis"]["cluster_size"])

        print(f"Decisions for 10 clean disputes from same merchant: {actions}")
        print(f"Graph risk scores: {set(risk_scores)}")
        print(f"Graph cluster sizes: {set(cluster_sizes)}")
        assert all(a == "AUTO-CONTEST" for a in actions)
        assert all(s == 0.0 for s in risk_scores)
        assert all(c == 1 for c in cluster_sizes)
        print("PROBE 2 RESULT: PASS\n")


def run_probe_3():
    print("=== PROBE 3: Mutated Replay Dispute ID Conflict Handling ===")
    os.environ["CHARGEBACK_ENV"] = "development"
    client = TestClient(app)

    payload_a = {
        "dispute_id": "REPLAY_CONFLICT_001",
        "payment_id": "pay_001",
        "reason_code": "item_not_received",
        "amount": 1500.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
    }
    resp1 = client.post("/score", json=payload_a)
    print(f"First request status: {resp1.status_code}")
    assert resp1.status_code == 200

    payload_b = dict(payload_a)
    payload_b["amount"] = 8500.0  # Mutated amount under same dispute_id
    resp2 = client.post("/score", json=payload_b)
    print(f"Mutated replay status: {resp2.status_code}, response: {resp2.json()}")
    assert resp2.status_code == 409
    assert resp2.json()["error"] == "payload_conflict"
    print("PROBE 3 RESULT: PASS\n")


def run_probe_4():
    print("=== PROBE 4: Fail-Field Hard Stop in Evidence ===")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "probe4_audit.db")
        # 2 PASS fields, 1 FAIL field
        dispute = {
            "dispute_id": "FAIL_FIELD_001",
            "reason_code": "item_not_received",
            "amount": 3000.0,
            "has_tracking_number": True,  # PASS
            "has_delivery_confirmation": True,  # PASS
            "has_signature_confirmation": False,  # FAIL
        }
        res = decide_case(dispute, db_path=db_path, include_counterfactual=False)
        print(f"Action: {res['action']}")
        print(f"Reason: {res['reason']}")
        print(f"Failed fields noted in reason: {'has_signature_confirmation' in res['reason']}")
        assert res["action"] == "HUMAN-REVIEW"
        assert "has_signature_confirmation" in res["reason"]
        print("PROBE 4 RESULT: PASS\n")


def run_probe_5():
    print("=== PROBE 5: Shared IP Damping & False-Positive Threshold ===")
    graph = RiskGraph()
    # 10 unrelated customers sharing only an IP address (e.g. coffee shop or corporate proxy)
    for i in range(10):
        graph.add(
            {
                "dispute_id": f"DISP_IP_{i:02d}",
                "customer_id": f"cust_ip_{i}",
                "ip_address": "192.0.2.1",
                "card_fingerprint": f"card_{i}",
                "device_id": f"device_{i}",
            }
        )
    analysis = graph.analyze(
        {
            "dispute_id": "DISP_IP_99",
            "customer_id": "cust_ip_99",
            "ip_address": "192.0.2.1",
            "card_fingerprint": "card_99",
            "device_id": "device_99",
        }
    )
    score = analysis.risk_score
    size = analysis.cluster_size
    print(f"Cluster size on shared IP: {size}")
    print(
        f"Risk score on shared IP: {score:.3f} (Escalation threshold is {GRAPH_ESCALATION_THRESHOLD})"
    )
    assert score < GRAPH_ESCALATION_THRESHOLD
    print("PROBE 5 RESULT: PASS\n")


def run_probe_6():
    print("=== PROBE 6: API Production Mode Authentication Enforcement ===")
    saved_env = os.environ.get("CHARGEBACK_ENV")
    saved_key = os.environ.get("CHARGEBACK_API_KEY")
    try:
        os.environ["CHARGEBACK_ENV"] = "production"
        if "CHARGEBACK_API_KEY" in os.environ:
            del os.environ["CHARGEBACK_API_KEY"]

        from chargeback_risk_engine.api import _validate_startup_config

        threw = False
        try:
            _validate_startup_config()
        except RuntimeError as e:
            threw = True
            print(f"Expected startup failure caught: {e}")
        assert threw is True
        print("PROBE 6 RESULT: PASS\n")
    finally:
        if saved_env is not None:
            os.environ["CHARGEBACK_ENV"] = saved_env
        else:
            os.environ.pop("CHARGEBACK_ENV", None)
        if saved_key is not None:
            os.environ["CHARGEBACK_API_KEY"] = saved_key
        else:
            os.environ.pop("CHARGEBACK_API_KEY", None)


def run_probe_7():
    print("=== PROBE 7: Model Artifact Tamper Detection ===")
    with tempfile.TemporaryDirectory() as tmp:
        model_path = os.path.join(tmp, "probe7_model.json")
        save_ml_scorer(path=model_path, train_csv="data/train.csv")

        # Tamper with the model file bytes
        with open(model_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        first_key = next(iter(data["models"]))
        data["models"][first_key]["intercept"][0] += 5.0
        with open(model_path, "wb") as f:
            f.write(json.dumps(data).encode("utf-8"))

        import chargeback_risk_engine.ml_scorer as ml_module

        ml_module._cached_scorer = None
        threw = False
        try:
            load_or_fit_ml_scorer(path=model_path, train_csv="data/train.csv")
        except ValueError as e:
            threw = True
            print(f"Tamper detected: {e}")
        assert threw is True
        print("PROBE 7 RESULT: PASS\n")


if __name__ == "__main__":
    run_probe_1()
    run_probe_2()
    run_probe_3()
    run_probe_4()
    run_probe_5()
    run_probe_6()
    run_probe_7()
    print("ALL 7 PROBES PASSED SUCCESSFULLY.")
