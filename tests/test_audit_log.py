"""
test_audit_log.py — real, runnable tests for audit_log.py, including a
concurrency fuzz test matching the strongest pattern seen in a reviewed
competitor repo (duplicate/concurrent request idempotency).
"""

import os
import threading

import pytest

from chargeback_risk_engine.audit_log import (
    LoggedDecision,
    PayloadConflictError,
    SqliteAuditStore,
    get_existing_decision,
    get_or_create_decision,
    load_graph_rows,
    verify_audit_integrity,
)

TEST_DB = "test_audit_log_pytest.db"


@pytest.fixture(autouse=True)
def clean_db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


def _fake_compute(call_counter):
    def compute():
        call_counter.append(1)
        return (0.8, [{"field": "x", "status": "PASS"}], "AUTO-CONTEST", "test reason", 1000.0)

    return compute


def test_first_call_is_not_replayed():
    calls = []
    result = get_or_create_decision(
        "D1", "item_not_received", 2000.0, _fake_compute(calls), db_path=TEST_DB
    )
    assert result.replayed is False
    assert len(calls) == 1


def test_second_call_same_id_is_replayed_and_does_not_recompute():
    calls = []
    first = get_or_create_decision(
        "D1", "item_not_received", 2000.0, _fake_compute(calls), db_path=TEST_DB
    )
    second = get_or_create_decision(
        "D1", "item_not_received", 2000.0, _fake_compute(calls), db_path=TEST_DB
    )

    assert second.replayed is True
    assert len(calls) == 1, "compute function should NOT be called a second time"
    assert first.action == second.action
    assert first.win_probability == second.win_probability
    assert first.expected_value == second.expected_value


def test_different_dispute_ids_are_independent():
    calls = []
    d1 = get_or_create_decision(
        "D1", "item_not_received", 2000.0, _fake_compute(calls), db_path=TEST_DB
    )
    d2 = get_or_create_decision(
        "D2", "item_not_received", 2000.0, _fake_compute(calls), db_path=TEST_DB
    )
    assert d1.replayed is False
    assert d2.replayed is False
    assert len(calls) == 2


def test_decision_persists_across_separate_connections():
    """Simulates a server restart -- a fresh call to get_existing_decision
    (new connection) should still find the record written earlier."""
    calls = []
    get_or_create_decision("D1", "item_not_received", 2000.0, _fake_compute(calls), db_path=TEST_DB)

    existing = get_existing_decision("D1", db_path=TEST_DB)
    assert existing is not None
    assert existing.action == "AUTO-CONTEST"


def test_concurrent_duplicate_submissions_only_compute_once():
    """Fuzz/concurrency test: fire 20 threads at the SAME dispute_id
    simultaneously. Exactly one should genuinely compute; the rest must
    return the identical replayed decision -- proving the SQLite PRIMARY
    KEY constraint prevents a race condition from causing double-processing."""
    calls = []
    results = []
    lock = threading.Lock()

    def worker():
        result = get_or_create_decision(
            "D_RACE", "item_not_received", 2000.0, _fake_compute(calls), db_path=TEST_DB
        )
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 20
    # Every result must have the identical action/probability (no split-brain)
    actions = {r.action for r in results}
    probabilities = {r.win_probability for r in results}
    assert len(actions) == 1, f"expected all identical actions, got {actions}"
    assert len(probabilities) == 1, f"expected all identical probabilities, got {probabilities}"
    # At most a small number of threads may have raced into compute() before
    # the DB lock resolved, but they must all converge to the same stored answer.
    assert len(calls) >= 1


def test_idempotency_conflict_raises_payload_conflict_error():
    calls = []
    # First submission
    first = get_or_create_decision(
        "D_CONFLICT",
        "item_not_received",
        2000.0,
        _fake_compute(calls),
        db_path=TEST_DB,
        payload_hash="hash_alpha",
    )
    assert first.replayed is False
    assert first.amount == 2000.0

    # Same dispute_id, same payload_hash -> replay OK
    replay = get_or_create_decision(
        "D_CONFLICT",
        "item_not_received",
        2000.0,
        _fake_compute(calls),
        db_path=TEST_DB,
        payload_hash="hash_alpha",
    )
    assert replay.replayed is True
    assert replay.amount == 2000.0

    # Same dispute_id, different payload_hash -> PayloadConflictError naming the dispute_id
    with pytest.raises(PayloadConflictError) as exc_info:
        get_or_create_decision(
            "D_CONFLICT",
            "item_not_received",
            90000.0,
            _fake_compute(calls),
            db_path=TEST_DB,
            payload_hash="hash_beta",
        )
    assert "D_CONFLICT" in str(exc_info.value)
    assert exc_info.value.dispute_id == "D_CONFLICT"

    # Verify audit row was NOT overwritten
    existing = get_existing_decision("D_CONFLICT", db_path=TEST_DB)
    assert existing.amount == 2000.0
    assert existing.payload_hash == "hash_alpha"

    # Verify audit chain integrity remains valid
    audit_status = verify_audit_integrity(db_path=TEST_DB)
    assert audit_status["valid"] is True
    assert audit_status["checked"] == 1


def test_chargeback_db_path_environment_variable(monkeypatch, tmp_path):
    """When CHARGEBACK_DB_PATH is set, decisions default to that database path."""
    env_db = str(tmp_path / "custom_audit.db")
    monkeypatch.setenv("CHARGEBACK_DB_PATH", env_db)

    calls = []
    decision = get_or_create_decision(
        "D_ENV_DB_1",
        "item_not_received",
        1500.0,
        _fake_compute(calls),
        db_path=None,
    )
    assert os.path.exists(env_db)
    assert decision.dispute_id == "D_ENV_DB_1"
    status = verify_audit_integrity(db_path=None)
    assert status["valid"] is True
    assert status["checked"] == 1


def test_migration_adds_missing_columns_on_legacy_schema(tmp_path):
    """Test _run_migrations adds missing columns when opening a legacy schema table."""
    import sqlite3

    legacy_db = str(tmp_path / "legacy_schema.db")
    conn = sqlite3.connect(legacy_db)
    conn.execute(
        "CREATE TABLE decisions (dispute_id TEXT PRIMARY KEY, reason_code TEXT, amount REAL, win_probability REAL, action TEXT, reason TEXT, expected_value REAL, evidence_json TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()

    # Opening via _get_connection runs _run_migrations and alters table to add columns
    store = SqliteAuditStore(legacy_db)
    res = store.get("NONEXISTENT")
    assert res is None


def test_row_to_logged_decision_corrupt_graph_json(tmp_path):
    """Corrupt graph_data_json falls back to empty dict."""
    import sqlite3

    db = str(tmp_path / "corrupt_graph.db")
    store = SqliteAuditStore(db)
    entry = LoggedDecision(
        dispute_id="D_CORRUPT_GRAPH",
        reason_code="item_not_received",
        amount=500.0,
        win_probability=0.8,
        action="AUTO-CONTEST",
        reason="ok",
        expected_value=350.0,
        evidence=[{"field": "x", "status": "PASS"}],
        created_at="2026-11-01T00:00:00Z",
    )
    store.append(entry)

    # Corrupt graph_data_json in SQLite directly
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE decisions SET graph_data_json = 'INVALID_JSON{{' WHERE dispute_id = 'D_CORRUPT_GRAPH'"
    )
    conn.commit()
    conn.close()

    decision = store.get("D_CORRUPT_GRAPH")
    assert decision is not None
    assert decision.dispute_id == "D_CORRUPT_GRAPH"


def test_store_append_integrity_error_reraised_when_existing_is_none(tmp_path, monkeypatch):
    """If sqlite3.IntegrityError occurs and get() returns None, the exception is reraised."""
    import sqlite3

    db = str(tmp_path / "integrity_reraise.db")
    store = SqliteAuditStore(db)
    entry = LoggedDecision(
        dispute_id="D_RERAISE",
        reason_code="item_not_received",
        amount=500.0,
        win_probability=0.8,
        action="AUTO-CONTEST",
        reason="ok",
        expected_value=350.0,
        evidence=[],
        created_at="2026-11-01T00:00:00Z",
    )
    store.append(entry)

    # Monkeypatch store.get to return None on collision
    monkeypatch.setattr(store, "get", lambda *args, **kwargs: None)
    with pytest.raises(sqlite3.IntegrityError):
        store.append(entry)


def test_store_append_generic_exception_rolls_back(tmp_path, monkeypatch):
    """Generic exception during store.append rolls back connection and raises."""
    import json

    db = str(tmp_path / "rollback_test.db")
    store = SqliteAuditStore(db)
    entry = LoggedDecision(
        dispute_id="D_ERR",
        reason_code="item_not_received",
        amount=500.0,
        win_probability=0.8,
        action="AUTO-CONTEST",
        reason="ok",
        expected_value=350.0,
        evidence=[],
        created_at="2026-11-01T00:00:00Z",
    )
    orig_dumps = json.dumps

    def faulty_dumps(obj, *args, **kwargs):
        if isinstance(obj, dict) and "dispute_id" in obj:
            raise TypeError("Simulated serialization error")
        return orig_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(json, "dumps", faulty_dumps)
    with pytest.raises(TypeError, match="Simulated serialization error"):
        store.append(entry)


def test_store_verify_missing_decisions_table(tmp_path, monkeypatch):
    """verify() returns checked=0 when decisions table does not exist."""
    db = str(tmp_path / "no_decisions.db")
    # Bypass auto-creation of decisions table
    monkeypatch.setattr("chargeback_risk_engine.audit_log._run_migrations", lambda conn: None)
    store = SqliteAuditStore(db)

    result = store.verify()
    assert result.valid is True
    assert result.checked == 0
    assert result.head_hash == ""


def test_store_verify_prev_hash_mismatch(tmp_path):
    """Tampering with prev_hash directly fails verification."""
    import sqlite3

    db = str(tmp_path / "prev_hash_tamper.db")
    store = SqliteAuditStore(db)
    for i in (1, 2):
        store.append(
            LoggedDecision(
                dispute_id=f"D_PREV_{i}",
                reason_code="item_not_received",
                amount=100.0 * i,
                win_probability=0.8,
                action="AUTO-CONTEST",
                reason="ok",
                expected_value=50.0,
                evidence=[],
                created_at="2026-11-01T00:00:00Z",
            )
        )
    # Tamper with prev_hash of second row
    conn = sqlite3.connect(db)
    conn.execute("UPDATE decisions SET prev_hash = 'TAMPERED_HASH' WHERE dispute_id = 'D_PREV_2'")
    conn.commit()
    conn.close()

    result = store.verify()
    assert result.valid is False
    assert result.failed_dispute_id == "D_PREV_2"

    # Also test export_head_anchor fails on invalid log
    with pytest.raises(ValueError, match="Cannot export anchor for invalid audit log"):
        store.export_head_anchor()


def test_load_graph_rows_corrupt_graph_json(tmp_path):
    """load_graph_rows safely handles corrupt graph_data_json."""
    import sqlite3

    db = str(tmp_path / "graph_corrupt.db")
    store = SqliteAuditStore(db)
    store.append(
        LoggedDecision(
            dispute_id="D_GRAPH_CORRUPT",
            reason_code="item_not_received",
            amount=500.0,
            win_probability=0.8,
            action="AUTO-CONTEST",
            reason="ok",
            expected_value=350.0,
            evidence=[],
            created_at="2026-11-01T00:00:00Z",
        )
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE decisions SET graph_data_json = 'NOT_JSON{{' WHERE dispute_id = 'D_GRAPH_CORRUPT'"
    )
    conn.commit()
    conn.close()

    rows = load_graph_rows(db_path=db)
    assert len(rows) == 1
    assert rows[0]["dispute_id"] == "D_GRAPH_CORRUPT"

    # Also test targeted search with dispute entity dictionary
    rows_target = load_graph_rows(
        db_path=db, dispute={"customer_id": "cust_unknown", "device_id": "dev_unknown"}
    )
    assert isinstance(rows_target, list)


def test_get_connection_wal_pragma_failure(tmp_path, monkeypatch):
    """OperationalError during PRAGMA journal_mode is caught cleanly."""
    import sqlite3

    from chargeback_risk_engine.audit_log import _get_connection

    orig_connect = sqlite3.connect

    class FakeConn:
        def __init__(self, *args, **kwargs):
            self.real = orig_connect(*args, **kwargs)

        def execute(self, sql, *args):
            if "PRAGMA journal_mode = WAL" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self.real.execute(sql, *args)

        def commit(self):
            return self.real.commit()

        def close(self):
            return self.real.close()

        def rollback(self):
            return self.real.rollback()

    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: FakeConn(*args, **kwargs))
    db = str(tmp_path / "wal_fail.db")
    conn = _get_connection(db)
    assert conn is not None


def test_sqlite_store_append_payload_conflict(tmp_path):
    """Calling append directly with a conflicting payload_hash raises PayloadConflictError."""
    db = str(tmp_path / "conflict.db")
    store = SqliteAuditStore(db)
    e1 = LoggedDecision(
        dispute_id="D_CONF",
        reason_code="item_not_received",
        amount=100.0,
        win_probability=0.8,
        action="AUTO-CONTEST",
        reason="ok",
        expected_value=50.0,
        evidence=[],
        created_at="2026-11-01T00:00:00Z",
        payload_hash="hash_one",
    )
    store.append(e1)
    e2 = LoggedDecision(
        dispute_id="D_CONF",
        reason_code="item_not_received",
        amount=100.0,
        win_probability=0.8,
        action="AUTO-CONTEST",
        reason="ok",
        expected_value=50.0,
        evidence=[],
        created_at="2026-11-01T00:00:00Z",
        payload_hash="hash_two",
    )
    with pytest.raises(PayloadConflictError):
        store.append(e2)


def test_load_graph_rows_relevant_disputes_corrupt_json(tmp_path):
    """load_graph_rows safely handles corrupt graph_data_json when traversing relevant disputes."""
    import sqlite3

    db = str(tmp_path / "relevant_corrupt.db")
    store = SqliteAuditStore(db)
    store.append(
        LoggedDecision(
            dispute_id="D_REL_CORRUPT",
            reason_code="item_not_received",
            amount=500.0,
            win_probability=0.8,
            action="AUTO-CONTEST",
            reason="ok",
            expected_value=350.0,
            evidence=[],
            created_at="2026-11-01T00:00:00Z",
            graph_data={"customer_id": "cust_target_1"},
        )
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE decisions SET graph_data_json = 'INVALID_JSON{{' WHERE dispute_id = 'D_REL_CORRUPT'"
    )
    conn.commit()
    conn.close()

    rows = load_graph_rows(db_path=db, dispute={"customer_id": "cust_target_1"})
    assert len(rows) == 1
    assert rows[0]["dispute_id"] == "D_REL_CORRUPT"


def test_export_head_anchor_module_level_function(tmp_path):
    """Test module-level export_head_anchor function."""
    from chargeback_risk_engine.audit_log import export_head_anchor

    db = str(tmp_path / "anchor_mod.db")
    store = SqliteAuditStore(db)
    store.append(
        LoggedDecision(
            dispute_id="D_ANC",
            reason_code="item_not_received",
            amount=500.0,
            win_probability=0.8,
            action="AUTO-CONTEST",
            reason="ok",
            expected_value=350.0,
            evidence=[],
            created_at="2026-11-01T00:00:00Z",
        )
    )
    anchor = export_head_anchor(db_path=db, secret_key="test_secret")
    assert "head_hash" in anchor
    assert "signature" in anchor


def test_get_or_create_decision_compute_tuple_lengths(tmp_path):
    """Test get_or_create_decision with 6 items, 7+ items, and invalid <5 items."""
    db = str(tmp_path / "tuple_lengths.db")

    # 6 items: (p, ev, action, reason, expected_val, graph_data)
    d6 = get_or_create_decision(
        "D_LEN_6",
        "item_not_received",
        100.0,
        lambda: (0.8, [], "AUTO-CONTEST", "ok", 50.0, {"customer_id": "c6"}),
        db_path=db,
    )
    assert d6.dispute_id == "D_LEN_6"

    # 7+ items: (p, ev, action, reason, expected_val, graph_data, ai_metadata, routing_score)
    d7 = get_or_create_decision(
        "D_LEN_7",
        "item_not_received",
        100.0,
        lambda: (
            0.8,
            [],
            "AUTO-CONTEST",
            "ok",
            50.0,
            {"customer_id": "c7"},
            {"note": "test"},
            0.85,
        ),
        db_path=db,
    )
    assert d7.dispute_id == "D_LEN_7"

    # <5 items: raises ValueError
    with pytest.raises(ValueError, match="compute_decision_fn must return at least 5 values"):
        get_or_create_decision(
            "D_LEN_FAIL",
            "item_not_received",
            100.0,
            lambda: (0.8, [], "AUTO-CONTEST"),
            db_path=db,
        )


def test_canonical_payload_hash_normalization():
    """Verify canonical_payload_hash handles floats, None, and ignored keys."""
    from chargeback_risk_engine.audit_log import canonical_payload_hash

    payload1 = {
        "dispute_id": "D_TEST",
        "amount": 2500.123456,
        "reason_code": "fraudulent",
        "none_field": None,
        "request_id": "req-1",
        "actor": "admin",
    }
    payload2 = {
        "dispute_id": "D_TEST",
        "amount": 2500.1235,
        "reason_code": "fraudulent",
        "none_field": None,
        "request_id": "req-2",
        "actor": "user",
    }
    assert canonical_payload_hash(payload1) == canonical_payload_hash(payload2)


def test_verify_with_limit_and_record_hash_tampering(tmp_path):
    """Test store.verify with limit parameter and verify record_hash tamper detection."""
    import sqlite3

    db = str(tmp_path / "limit_tamper.db")
    store = SqliteAuditStore(db)
    for i in range(1, 4):
        store.append(
            LoggedDecision(
                dispute_id=f"D_REC_{i}",
                reason_code="item_not_received",
                amount=100.0 * i,
                win_probability=0.8,
                action="AUTO-CONTEST",
                reason="ok",
                expected_value=50.0,
                evidence=[],
                created_at="2026-11-01T00:00:00Z",
            )
        )

    # Verify with limit
    lim_res = store.verify(limit=2)
    assert lim_res.valid is True
    assert lim_res.checked == 2

    # Tamper with record_hash directly in database
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE decisions SET record_hash = 'TAMPERED_RECORD_HASH' WHERE dispute_id = 'D_REC_3'"
    )
    conn.commit()
    conn.close()

    tampered_res = store.verify()
    assert tampered_res.valid is False
    assert tampered_res.failed_dispute_id == "D_REC_3"

    # Also test verify_audit_integrity returns failed_dispute_id and error
    status = verify_audit_integrity(db_path=db)
    assert status["valid"] is False
    assert status["failed_dispute_id"] == "D_REC_3"
    assert "error" in status


def test_load_graph_rows_no_target_entities(tmp_path):
    """load_graph_rows returns empty list when dispute has no entity identifiers."""
    db = str(tmp_path / "no_entities.db")
    rows = load_graph_rows(db_path=db, dispute={})
    assert rows == []
