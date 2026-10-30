from concurrent.futures import ThreadPoolExecutor
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


def test_hash_chain_concurrent_inserts_no_forks(tmp_path: Path):
    """Multiple concurrent worker threads inserting records must not fork the hash chain."""
    db = str(tmp_path / "concurrent_audit.db")
    total_records = 30

    def insert_worker(i: int):
        get_or_create_decision(
            dispute_id=f"CONCURRENT_{i}",
            reason_code="item_not_received",
            amount=1000.0 + i,
            compute_decision_fn=lambda: (
                0.8,
                [{"field": "has_tracking_number", "status": "PASS"}],
                "AUTO-CONTEST",
                "ok",
                650.0 + i,
            ),
            db_path=db,
            request_id=f"req-thread-{i}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(insert_worker, range(total_records)))

    result = verify_audit_integrity(db)
    assert result["valid"] is True, f"Audit hash chain forked or invalid under concurrency: {result}"
    assert result["checked"] == total_records
    assert result["head_hash"]
