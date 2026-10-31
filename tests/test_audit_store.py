"""Contract tests for AuditStore protocol and concurrency validation."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

from chargeback_risk_engine.audit_log import (
    AuditStore,
    LoggedDecision,
    SQLiteAuditStore,
)


def test_sqlite_audit_store_satisfies_protocol(tmp_path: Path):
    db_file = tmp_path / "test_contract.db"
    store: AuditStore = SQLiteAuditStore(str(db_file))
    assert isinstance(store, AuditStore)


def test_audit_store_append_and_verify(tmp_path: Path):
    db_file = tmp_path / "test_store.db"
    store = SQLiteAuditStore(str(db_file))

    entry = LoggedDecision(
        dispute_id="D_TEST_001",
        reason_code="item_not_received",
        amount=1500.0,
        win_probability=0.75,
        action="AUTO-CONTEST",
        reason="high win probability",
        expected_value=975.0,
        evidence=[{"field": "has_tracking_number", "status": "PASS"}],
        created_at="2026-10-31T12:00:00Z",
        actor="worker_1",
    )

    appended = store.append(entry)
    assert appended.record_hash
    assert appended.prev_hash == ""

    # Fetch
    fetched = store.get("D_TEST_001")
    assert fetched is not None
    assert fetched.dispute_id == "D_TEST_001"
    assert fetched.actor == "worker_1"
    assert store.head() == appended.record_hash

    # Verification
    res = store.verify()
    assert res.valid is True
    assert res.checked == 1
    assert res.head_hash == appended.record_hash


def test_audit_store_concurrency_stress(tmp_path: Path):
    """8 concurrent workers writing 50 entries each (400 total) without lock failure or chain break."""
    db_file = tmp_path / "concurrency_stress.db"
    store = SQLiteAuditStore(str(db_file))

    num_threads = 8
    writes_per_thread = 50
    total_writes = num_threads * writes_per_thread

    def worker_task(thread_id: int):
        results = []
        for i in range(writes_per_thread):
            disp_id = f"TH_{thread_id}_DISP_{i:03d}"
            entry = LoggedDecision(
                dispute_id=disp_id,
                reason_code="item_not_received",
                amount=2000.0 + i,
                win_probability=0.70,
                action="AUTO-CONTEST",
                reason=f"worker_{thread_id}_write_{i}",
                expected_value=1250.0,
                evidence=[{"field": "has_tracking_number", "status": "PASS"}],
                created_at="2026-10-31T12:00:00Z",
                actor=f"worker_{thread_id}",
            )
            appended = store.append(entry)
            results.append(appended.record_hash)
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_task, tid) for tid in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            hashes = f.result()
            assert len(hashes) == writes_per_thread

    # Verify all records exist and the hash chain is strictly contiguous and unbroken
    verification = store.verify()
    assert verification.valid is True
    assert verification.checked == total_writes


def test_export_head_anchor(tmp_path: Path):
    db_file = tmp_path / "anchor_test.db"
    store = SQLiteAuditStore(str(db_file))

    entry = LoggedDecision(
        dispute_id="D_ANCHOR_1",
        reason_code="duplicate_charge",
        amount=500.0,
        win_probability=0.90,
        action="AUTO-CONTEST",
        reason="clear duplicate charge",
        expected_value=300.0,
        evidence=[],
        created_at="2026-10-31T12:00:00Z",
    )
    store.append(entry)

    anchor = store.export_head_anchor(secret_key="test_signing_key_123")
    assert "timestamp" in anchor
    assert "head_hash" in anchor
    assert anchor["row_count"] == 1
    assert "signature" in anchor
    assert len(anchor["signature"]) == 64
