"""Fast, judge-friendly release verification without the LLM/API path."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chargeback_risk_engine.audit_log import log_new_decision, verify_audit_integrity
from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.independent_verifier import verify_decision
from chargeback_risk_engine.paths import ARTIFACTS_DIR
from chargeback_risk_engine.policy import decide
from chargeback_risk_engine.policy_profile import load_policy_profile, decision_score

CASES = [
    {
        "dispute_id": "RV_POS",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    },
    {
        "dispute_id": "RV_WARN",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": None,
        "has_signature_confirmation": None,
    },
    {
        "dispute_id": "RV_CEIL",
        "reason_code": "item_not_received",
        "amount": 75000.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    },
]


def main() -> int:
    profile = load_policy_profile()
    results = []
    with tempfile.TemporaryDirectory(prefix="release_verify_") as tmp:
        db = str(Path(tmp) / "audit.db")
        for case in CASES:
            packet = assemble(case)
            quality = score_evidence(case, packet)
            # Fixed synthetic probability used only to exercise deterministic
            # release verification. This is not a model-performance claim.
            p = 0.80
            score = decision_score(p, quality.confidence, evidence_signal_weight=profile.evidence_signal_weight)
            econ = calculate_economic_value(case["amount"], p)
            decision = decide(
                p, case["amount"], evidence_packet=packet, evidence_quality=quality,
                expected_net_value=econ.expected_net_value, decision_score=score,
                auto_contest_threshold=profile.auto_contest_threshold,
                accept_loss_threshold=profile.accept_loss_threshold,
                monetary_ceiling=profile.monetary_ceiling,
                min_evidence_completeness=profile.min_evidence_completeness,
            )
            result = {
                "dispute_id": case["dispute_id"], "action": decision.action,
                "win_probability": p, "routing_score": score, "amount": case["amount"],
                "economic_decision": econ.to_dict(), "evidence_score": quality.to_dict(),
                "graph_analysis": {"risk_score": 0.0},
            }
            checked = verify_decision(result)
            log_new_decision(case["dispute_id"], case["reason_code"], case["amount"], p,
                             decision.action, decision.reason, decision.expected_value,
                             [{"field": i.field, "status": i.status} for i in packet.items],
                             db_path=db, model_version="release-test", feature_version="release-test",
                             policy_version=profile.profile_version, routing_score=score)
            results.append({"case": case["dispute_id"], "action": decision.action, **checked})
        audit = verify_audit_integrity(db)
    report = {"valid": all(r["valid"] for r in results) and audit["valid"], "decisions": results, "audit": audit}
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    # Generated locally for release checks; intentionally ignored by Git.
    (ARTIFACTS_DIR / "release_verification.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
