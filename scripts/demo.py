"""Five deterministic product scenarios using the canonical decision service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.risk_graph import RiskGraph


def main() -> None:
    db = "demo_audit.db"
    if os.path.exists(db):
        os.remove(db)

    historical_ring = [
        {"dispute_id": "R1", "customer_id": "c1", "device_id": "shared-device", "ip_address": "10.0.0.9", "amount": 1800},
        {"dispute_id": "R2", "customer_id": "c2", "device_id": "shared-device", "ip_address": "10.0.0.9", "amount": 2200},
        {"dispute_id": "R3", "customer_id": "c3", "device_id": "shared-device", "ip_address": "10.0.0.9", "amount": 1600},
        {"dispute_id": "R4", "customer_id": "c4", "device_id": "shared-device", "ip_address": "10.0.0.8", "amount": 1900},
        {"dispute_id": "R5", "customer_id": "c5", "device_id": "shared-device", "ip_address": "10.0.0.8", "amount": 2100},
    ]
    cases = [
        ("CASE_1_AUTO_CONTEST", {"dispute_id":"DEMO_AUTO","payment_id":"pay_demo_1","reason_code":"item_not_received","amount":2400.0,"customer_id":"demo_customer_unique","device_id":"unique-device","ip_address":"10.0.0.99","merchant_id":"merchant_demo","has_tracking_number":True,"has_delivery_confirmation":True,"has_signature_confirmation":True}),
        ("CASE_2_HUMAN_REVIEW", {"dispute_id":"DEMO_REVIEW","payment_id":"pay_demo_2","reason_code":"item_not_received","amount":2400.0,"customer_id":"missing_customer","device_id":"missing-device","ip_address":"10.0.0.77","merchant_id":"merchant_demo","has_tracking_number":True,"has_delivery_confirmation":None,"has_signature_confirmation":None}),
        ("CASE_3_GRAPH_ESCALATION", {"dispute_id":"DEMO_RING","payment_id":"pay_demo_3","reason_code":"item_not_received","amount":2400.0,"customer_id":"demo_customer_ring","device_id":"shared-device","ip_address":"10.0.0.9","merchant_id":"merchant_demo","has_tracking_number":True,"has_delivery_confirmation":True,"has_signature_confirmation":True}),
        ("CASE_4_WEAK_EVIDENCE", {"dispute_id":"DEMO_WEAK","payment_id":"pay_demo_4","reason_code":"item_not_as_described","amount":1800.0,"customer_id":"demo_customer_weak","device_id":"weak-device","has_product_photos":None,"has_item_description_match":False,"has_return_communication":None}),
        ("CASE_5_ECONOMIC_BOUNDARY", {"dispute_id":"DEMO_ECON","payment_id":"pay_demo_5","reason_code":"duplicate_charge","amount":500.0,"customer_id":"demo_customer_econ","device_id":"econ-device","has_duplicate_transaction_proof":True,"has_refund_already_issued":False}),
    ]
    for label, case in cases:
        result = decide_case(case, risk_graph=RiskGraph(historical_ring), db_path=db)
        print(f"\n=== {label} ===")
        print(json.dumps({
            "dispute_id": result["dispute_id"],
            "decision": result["action"],
            "win_probability": result["win_probability"],
            "evidence": result["evidence"],
            "expected_net_value": result["economic_decision"]["expected_net_value"],
            "why": result["explanation"]["policy_reason"],
            "what_would_change": result["counterfactual"]["statement"],
            "audit_id": result["audit_id"],
        }, indent=2))


    os.remove(db)


if __name__ == "__main__":
    main()
