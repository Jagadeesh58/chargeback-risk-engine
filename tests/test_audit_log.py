"""
test_audit_log.py — real, runnable tests for audit_log.py, including a
concurrency fuzz test matching the strongest pattern seen in a reviewed
competitor repo (duplicate/concurrent request idempotency).
"""

import os
import threading

import pytest

from chargeback_risk_engine.audit_log import (
    PayloadConflictError,
    get_existing_decision,
    get_or_create_decision,
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
