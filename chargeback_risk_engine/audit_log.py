"""
audit_log.py — persistent SQLite audit trail + idempotency guarantee.

The audit log stores the original evidence and relationship identifiers used for
each decision. Replays can therefore reconstruct the ORIGINAL request context
instead of accidentally using fields from a mutated retry payload.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from chargeback_risk_engine.paths import REPO_ROOT

DB_PATH = str(REPO_ROOT / "audit_log.db")


def _get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
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
            created_at TEXT NOT NULL,
            model_version TEXT NOT NULL DEFAULT 'rules-v1',
            feature_version TEXT NOT NULL DEFAULT 'features-v1',
            policy_version TEXT NOT NULL DEFAULT 'policy-v1',
            graph_data_json TEXT NOT NULL DEFAULT '{}',
            ai_metadata_json TEXT NOT NULL DEFAULT '{}',
            request_id TEXT NOT NULL DEFAULT '',
            prev_hash TEXT NOT NULL DEFAULT '',
            record_hash TEXT NOT NULL DEFAULT ''
        )
    """)
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()
    }
    migrations = {
        "model_version": "TEXT NOT NULL DEFAULT 'unknown'",
        "feature_version": "TEXT NOT NULL DEFAULT 'unknown'",
        "policy_version": "TEXT NOT NULL DEFAULT 'unknown'",
        "graph_data_json": "TEXT NOT NULL DEFAULT '{}'",
        "ai_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "request_id": "TEXT NOT NULL DEFAULT ''",
        "prev_hash": "TEXT NOT NULL DEFAULT ''",
        "record_hash": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in migrations.items():
        if name not in existing_columns:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {name} {definition}")
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
    model_version: str = "rules-v1"
    feature_version: str = "features-v1"
    policy_version: str = "policy-v1"
    graph_data: dict | None = None
    ai_metadata: dict | None = None
    request_id: str = ""
    prev_hash: str = ""
    record_hash: str = ""
    replayed: bool = False


def _row_to_logged_decision(record: dict, *, replayed: bool) -> LoggedDecision:
    graph_raw = record.get("graph_data_json") or "{}"
    try:
        graph_data = json.loads(graph_raw)
    except (TypeError, json.JSONDecodeError):
        graph_data = {}
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
        model_version=record.get("model_version", "unknown"),
        feature_version=record.get("feature_version", "unknown"),
        policy_version=record.get("policy_version", "unknown"),
        graph_data=graph_data,
        ai_metadata=json.loads(record.get("ai_metadata_json") or "{}"),
        request_id=record.get("request_id", ""),
        prev_hash=record.get("prev_hash", ""),
        record_hash=record.get("record_hash", ""),
        replayed=replayed,
    )


def get_existing_decision(dispute_id: str, db_path: str = DB_PATH) -> LoggedDecision | None:
    """Return the already-logged decision for this dispute_id, if present."""
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("SELECT * FROM decisions WHERE dispute_id = ?", (dispute_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [d[0] for d in cursor.description]
        return _row_to_logged_decision(dict(zip(columns, row)), replayed=True)
    finally:
        conn.close()


def load_graph_rows(db_path: str = DB_PATH) -> list[dict]:
    """Load historical relationship rows from the audit log for graph analysis."""
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT dispute_id, amount, graph_data_json FROM decisions WHERE graph_data_json != '{}'"
        )
        rows = []
        for dispute_id, amount, graph_data_json in cursor.fetchall():
            try:
                graph_data = json.loads(graph_data_json or "{}")
            except (TypeError, json.JSONDecodeError):
                graph_data = {}
            rows.append({"dispute_id": dispute_id, "amount": amount, **graph_data})
        return rows
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
    model_version: str = "rules-v1",
    feature_version: str = "features-v1",
    policy_version: str = "policy-v1",
    graph_data: dict | None = None,
    ai_metadata: dict | None = None,
    request_id: str = "",
) -> LoggedDecision:
    """Persist a new decision without replacing an existing dispute_id."""
    created_at = datetime.now(timezone.utc).isoformat()
    graph_data = graph_data or {}
    ai_metadata = ai_metadata or {}
    conn = _get_connection(db_path)
    try:
        prev_row = conn.execute("SELECT record_hash FROM decisions ORDER BY created_at DESC, dispute_id DESC LIMIT 1").fetchone()
        prev_hash = prev_row[0] if prev_row and prev_row[0] else ""
        payload = {"dispute_id": dispute_id, "reason_code": reason_code, "amount": float(amount), "win_probability": float(win_probability),
                   "action": action, "reason": reason, "expected_value": float(expected_value), "evidence": evidence,
                   "created_at": created_at, "model_version": model_version, "feature_version": feature_version,
                   "policy_version": policy_version, "graph_data": graph_data, "ai_metadata": ai_metadata,
                   "request_id": request_id, "prev_hash": prev_hash}
        record_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        conn.execute(
            """INSERT INTO decisions
               (dispute_id, reason_code, amount, win_probability, action,
                reason, expected_value, evidence_json, created_at,
                model_version, feature_version, policy_version, graph_data_json, ai_metadata_json, request_id, prev_hash, record_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dispute_id, reason_code, amount, win_probability, action, reason, expected_value,
             json.dumps(evidence, sort_keys=True), created_at, model_version, feature_version, policy_version,
             json.dumps(graph_data, sort_keys=True), json.dumps(ai_metadata, sort_keys=True), request_id, prev_hash, record_hash),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Another concurrent request won the insert race. Replay its durable row.
        existing = get_existing_decision(dispute_id, db_path)
        if existing is None:
            raise
        return existing
    finally:
        conn.close()

    return LoggedDecision(
        dispute_id=dispute_id,
        reason_code=reason_code,
        amount=amount,
        win_probability=win_probability,
        action=action,
        reason=reason,
        expected_value=expected_value,
        evidence=evidence,
        created_at=created_at,
        model_version=model_version,
        feature_version=feature_version,
        policy_version=policy_version,
        graph_data=graph_data,
        ai_metadata=ai_metadata,
        request_id=request_id,
        prev_hash=prev_hash,
        record_hash=record_hash,
        replayed=False,
    )



def verify_audit_integrity(db_path: str = DB_PATH) -> dict:
    conn = _get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM decisions ORDER BY created_at ASC, dispute_id ASC").fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM decisions LIMIT 0").description]
        prev_hash = ""
        checked = 0
        for row in rows:
            rec = dict(zip(cols, row))
            expected_payload = {"dispute_id": rec["dispute_id"], "reason_code": rec["reason_code"], "amount": float(rec["amount"]), "win_probability": float(rec["win_probability"]),
                "action": rec["action"], "reason": rec["reason"], "expected_value": float(rec["expected_value"]), "evidence": json.loads(rec["evidence_json"]),
                "created_at": rec["created_at"], "model_version": rec["model_version"], "feature_version": rec["feature_version"],
                "policy_version": rec["policy_version"], "graph_data": json.loads(rec["graph_data_json"] or "{}"), "ai_metadata": json.loads(rec.get("ai_metadata_json") or "{}"),
                "request_id": rec.get("request_id", ""), "prev_hash": rec.get("prev_hash", "") }
            expected = hashlib.sha256(json.dumps(expected_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if rec.get("prev_hash", "") != prev_hash or rec.get("record_hash", "") != expected:
                return {"valid": False, "checked": checked, "failed_dispute_id": rec["dispute_id"]}
            prev_hash = expected
            checked += 1
        return {"valid": True, "checked": checked, "head_hash": prev_hash}
    finally:
        conn.close()

def get_or_create_decision(
    dispute_id: str,
    reason_code: str,
    amount: float,
    compute_decision_fn,
    db_path: str = DB_PATH,
    model_version: str = "rules-v1",
    feature_version: str = "features-v1",
    policy_version: str = "policy-v1",
    ai_metadata: dict | None = None,
    request_id: str = "",
) -> LoggedDecision:
    """Return an existing decision or compute and persist a new one.

    For backward compatibility, compute_decision_fn may return either:
      (probability, evidence, action, reason, expected_value)
    or the same five values plus graph_data and AI metadata.
    """
    existing = get_existing_decision(dispute_id, db_path)
    if existing is not None:
        return existing

    computed = compute_decision_fn()
    if len(computed) == 5:
        win_probability, evidence, action, reason, expected_value = computed
        graph_data = {}
        ai_metadata = ai_metadata or None
    elif len(computed) == 6:
        win_probability, evidence, action, reason, expected_value, graph_data = computed
        ai_metadata = None
    elif len(computed) == 7:
        win_probability, evidence, action, reason, expected_value, graph_data, ai_metadata = computed
    else:
        raise ValueError("compute_decision_fn must return 5, 6, or 7 values")

    return log_new_decision(
        dispute_id=dispute_id,
        reason_code=reason_code,
        amount=amount,
        win_probability=win_probability,
        action=action,
        reason=reason,
        expected_value=expected_value,
        evidence=evidence,
        db_path=db_path,
        model_version=model_version,
        feature_version=feature_version,
        policy_version=policy_version,
        graph_data=graph_data,
        ai_metadata=ai_metadata,
        request_id=request_id,
    )
