"""CLI demo of the production-minded hybrid decision flow."""
from pathlib import Path
import sys

# Allow direct execution from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



import json
import os

from chargeback_risk_engine.engine.hybrid_pipeline import score_hybrid
from chargeback_risk_engine.engine.risk_graph import RiskGraph


def main():
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
        ("strong evidence", {
            "dispute_id": "DEMO_STRONG", "payment_id": "pay_demo", "reason_code": "item_not_received",
            "amount": 2400.0, "customer_id": "demo_customer_unique", "device_id": "unique-device",
            "ip_address": "10.0.0.99", "merchant_id": "merchant_demo",
            "has_tracking_number": True, "has_delivery_confirmation": True, "has_signature_confirmation": True,
        }),
        ("missing evidence", {
            "dispute_id": "DEMO_MISSING", "payment_id": "pay_demo", "reason_code": "item_not_received",
            "amount": 2400.0, "customer_id": "missing_customer", "device_id": "missing-device",
            "ip_address": "10.0.0.77", "merchant_id": "merchant_demo",
            "has_tracking_number": True, "has_delivery_confirmation": None, "has_signature_confirmation": None,
        }),
        ("over ceiling", {
            "dispute_id": "DEMO_CEILING", "payment_id": "pay_demo", "reason_code": "item_not_received",
            "amount": 725000.0, "customer_id": "ceiling_customer", "device_id": "ceiling-device",
            "ip_address": "10.0.0.76", "merchant_id": "merchant_demo",
            "has_tracking_number": True, "has_delivery_confirmation": True, "has_signature_confirmation": True,
        }),
        ("contradictory evidence", {
            "dispute_id": "DEMO_CONFLICT", "payment_id": "pay_demo", "reason_code": "item_not_received",
            "amount": 2400.0, "customer_id": "demo_customer_ring", "device_id": "shared-device",
            "ip_address": "10.0.0.9", "merchant_id": "merchant_demo",
            "has_tracking_number": True, "has_delivery_confirmation": False, "has_signature_confirmation": True,
            "has_delivery_confirmation_consistent": False,
        }),
        ("abuse-ring escalation", {
            "dispute_id": "DEMO_RING", "payment_id": "pay_demo", "reason_code": "item_not_received",
            "amount": 2100.0, "customer_id": "c6", "device_id": "shared-device",
            "ip_address": "10.0.0.9", "merchant_id": "merchant_demo",
            "has_tracking_number": True, "has_delivery_confirmation": True, "has_signature_confirmation": True,
        }),
    ]

    for name, dispute in cases:
        print(f"\n=== {name.upper()} ===")
        print(json.dumps(score_hybrid(dispute, risk_graph=RiskGraph(historical_ring), db_path=db), indent=2))

    # Idempotency demonstration: same dispute_id replays the original decision.
    replay = cases[0][1].copy()
    replay["has_tracking_number"] = False
    print("\n=== DUPLICATE EVENT / IDEMPOTENT REPLAY ===")
    print(json.dumps(score_hybrid(replay, risk_graph=RiskGraph(historical_ring), db_path=db), indent=2))


if __name__ == "__main__":
    main()
