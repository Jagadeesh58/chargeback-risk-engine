from pathlib import Path
from chargeback_risk_engine.audit_log import get_or_create_decision, verify_audit_integrity


def test_hash_chain_verifies(tmp_path: Path):
    db = str(tmp_path / "audit.db")
    get_or_create_decision("A1", "item_not_received", 1000, lambda: (0.8, [{"field":"x","status":"PASS"}], "AUTO-CONTEST", "ok", 650), db_path=db, request_id="req-1")
    get_or_create_decision("A2", "item_not_received", 1000, lambda: (0.7, [{"field":"x","status":"PASS"}], "AUTO-CONTEST", "ok", 550), db_path=db, request_id="req-2")
    result = verify_audit_integrity(db)
    assert result["valid"] is True
    assert result["checked"] == 2
    assert result["head_hash"]
