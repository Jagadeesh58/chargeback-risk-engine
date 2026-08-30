"""
audit_log.py — persistent SQLite audit trail + idempotency guarantee.

Every scored dispute gets written to a local SQLite database (a single
file, audit_log.db -- no server, no setup). If the exact same
dispute_id is submitted again, the ORIGINAL decision is returned
instead of recomputing -- guaranteeing idempotency and providing a
permanent, inspectable record of every decision ever made.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

DB_PATH = "audit_log.db"


def _get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            dispute_id TEXT PRIMARY KEY,
            reason_code TEXT NOT NULL,
            amount REAL NOT NULL,
            win_probability REAL NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            expected_value REAL NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


@dataclass
class LoggedDecision:
    dispute_id: str
    reason_code: str
    amount: float
    win_probability: float
    action: str
    reason: str
    expected_value: float
    evidence: list
    created_at: str
    replayed: bool  # True if this was an idempotent replay, not a new decision


def get_existing_decision(dispute_id: str, db_path: str = DB_PATH) -> LoggedDecision | None:
    """Returns the already-logged decision for this dispute_id, or None
    if it's genuinely new."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM decisions WHERE dispute_id = ?", (dispute_id,)
        ).fetchone()
        if row is None:
            return None
        columns = [d[0] for d in conn.execute("SELECT * FROM decisions LIMIT 0").description]
        record = dict(zip(columns, row))
        return LoggedDecision(
            dispute_id=record["dispute_id"],
            reason_code=record["reason_code"],
            amount=record["amount"],
            win_probability=record["win_probability"],
            action=record["action"],
            reason=record["reason"],
            expected_value=record["expected_value"],
            evidence=json.loads(record["evidence_json"]),
            created_at=record["created_at"],
            replayed=True,
        )
    finally:
        conn.close()


def log_new_decision(
    dispute_id: str,
    reason_code: str,
    amount: float,
    win_probability: float,
    action: str,
    reason: str,
    expected_value: float,
    evidence: list,
    db_path: str = DB_PATH,
) -> LoggedDecision:
    """Writes a brand-new decision to the audit trail. Uses INSERT (not
    INSERT OR REPLACE) so the PRIMARY KEY constraint on dispute_id
    physically prevents a duplicate row, even under a race condition --
    matching the same idempotency guarantee style used in the competitor
    repo's SQLite PK-based approach."""
    created_at = datetime.now(timezone.utc).isoformat()
    conn = _get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO decisions
               (dispute_id, reason_code, amount, win_probability, action,
                reason, expected_value, evidence_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dispute_id, reason_code, amount, win_probability, action,
             reason, expected_value, json.dumps(evidence), created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Another concurrent request already inserted this dispute_id
        # first -- treat it the same as a replay, don't crash.
        conn.close()
        existing = get_existing_decision(dispute_id, db_path)
        assert existing is not None
        return existing
    finally:
        conn.close()

    return LoggedDecision(
        dispute_id=dispute_id, reason_code=reason_code, amount=amount,
        win_probability=win_probability, action=action, reason=reason,
        expected_value=expected_value, evidence=evidence,
        created_at=created_at, replayed=False,
    )


def get_or_create_decision(
    dispute_id: str, reason_code: str, amount: float,
    compute_decision_fn, db_path: str = DB_PATH,
) -> LoggedDecision:
    """The main entry point: checks the audit trail first. If this
    dispute_id was already decided, returns that EXACT original decision
    (idempotent replay). Only calls compute_decision_fn (the real
    scorer+evidence+policy pipeline) if it's genuinely new."""
    existing = get_existing_decision(dispute_id, db_path)
    if existing is not None:
        return existing

    win_probability, evidence, action, reason, expected_value = compute_decision_fn()
    return log_new_decision(
        dispute_id=dispute_id, reason_code=reason_code, amount=amount,
        win_probability=win_probability, action=action, reason=reason,
        expected_value=expected_value, evidence=evidence, db_path=db_path,
    )