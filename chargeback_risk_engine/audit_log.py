"""audit_log.py — persistent SQLite audit trail + idempotency guarantee.

The audit log stores the original evidence and relationship identifiers used for
each decision. Replays reconstruct the ORIGINAL request context instead of
accidentally using fields from a mutated retry payload.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from chargeback_risk_engine.paths import REPO_ROOT

DB_PATH = os.getenv("CHARGEBACK_DB_PATH") or str(REPO_ROOT / "audit_log.db")

_AUDIT_WRITE_LOCK = threading.Lock()


class PayloadConflictError(Exception):
    """Raised when an existing dispute_id is submitted with a conflicting payload."""

    def __init__(self, dispute_id: str, message: str | None = None):
        self.dispute_id = dispute_id
        super().__init__(
            message
            or f"Conflict: dispute_id '{dispute_id}' already exists with a different payload"
        )


def canonical_payload_hash(dispute: dict) -> str:
    """Deterministic SHA-256 hash of normalized dispute request payload."""
    ignored_keys = {
        "request_id",
        "created_at",
        "db_path",
        "risk_graph",
        "call_ai_analyst",
        "replayed",
        "actor",
    }
    normalized: dict[str, Any] = {}
    for k, v in dispute.items():
        if k in ignored_keys:
            continue
        if isinstance(v, float):
            normalized[k] = round(float(v), 4)
        elif v is not None:
            normalized[k] = v
        else:
            normalized[k] = None
    canonical_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply versioned schema migrations ensuring forward and backward compatibility."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)

    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

    # Migration 1: Base tables
    if 1 not in applied:
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
                routing_score REAL,
                prev_hash TEXT NOT NULL DEFAULT '',
                record_hash TEXT NOT NULL DEFAULT '',
                payload_hash TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_entities (
                dispute_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_value TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0.0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_entities_type_val ON graph_entities(entity_type, entity_value)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_entities_dispute_id ON graph_entities(dispute_id)"
        )
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (1, ?)", (now,)
        )

    # Migration 2: Actor provenance column
    if 2 not in applied:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
        if "actor" not in columns:
            conn.execute("ALTER TABLE decisions ADD COLUMN actor TEXT NOT NULL DEFAULT 'anonymous'")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (2, ?)", (now,)
        )

    # Backward compatibility column check
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
    migrations = {
        "model_version": "TEXT NOT NULL DEFAULT 'unknown'",
        "feature_version": "TEXT NOT NULL DEFAULT 'unknown'",
        "policy_version": "TEXT NOT NULL DEFAULT 'unknown'",
        "graph_data_json": "TEXT NOT NULL DEFAULT '{}'",
        "ai_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "request_id": "TEXT NOT NULL DEFAULT ''",
        "prev_hash": "TEXT NOT NULL DEFAULT ''",
        "record_hash": "TEXT NOT NULL DEFAULT ''",
        "routing_score": "REAL",
        "payload_hash": "TEXT NOT NULL DEFAULT ''",
        "actor": "TEXT NOT NULL DEFAULT 'anonymous'",
    }
    for name, definition in migrations.items():
        if name not in existing_columns:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {name} {definition}")

    conn.commit()


def _get_connection(db_path: str | None = None) -> sqlite3.Connection:
    effective_path = db_path or os.getenv("CHARGEBACK_DB_PATH") or DB_PATH
    conn = sqlite3.connect(effective_path, timeout=30)
    # Production SQLite hardening pragmas
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")

    _run_migrations(conn)
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
    routing_score: float | None = None
    prev_hash: str = ""
    record_hash: str = ""
    payload_hash: str = ""
    actor: str = "anonymous"
    replayed: bool = False


@dataclass
class AuditVerificationResult:
    valid: bool
    checked: int
    head_hash: str = ""
    failed_dispute_id: str | None = None
    error: str | None = None


@runtime_checkable
class AuditStore(Protocol):
    """Abstract Audit Store protocol for durable cryptographic audit logging."""

    def append(self, entry: LoggedDecision) -> LoggedDecision: ...

    def verify(self) -> AuditVerificationResult: ...

    def get(self, dispute_id: str) -> LoggedDecision | None: ...

    def head(self) -> str | None: ...


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
        routing_score=float(record["routing_score"])
        if record.get("routing_score") is not None
        else None,
        prev_hash=record.get("prev_hash", ""),
        record_hash=record.get("record_hash", ""),
        payload_hash=record.get("payload_hash", ""),
        actor=record.get("actor", "anonymous"),
        replayed=replayed,
    )


class SQLiteAuditStore:
    """Production SQLite-backed implementation of AuditStore with hash-chain integrity."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def get(self, dispute_id: str) -> LoggedDecision | None:
        conn = _get_connection(self.db_path)
        try:
            cursor = conn.execute("SELECT * FROM decisions WHERE dispute_id = ?", (dispute_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [d[0] for d in cursor.description]
            return _row_to_logged_decision(dict(zip(columns, row)), replayed=True)
        finally:
            conn.close()

    def head(self) -> str | None:
        conn = _get_connection(self.db_path)
        try:
            cursor = conn.execute("SELECT record_hash FROM decisions ORDER BY rowid DESC LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row and row[0] else None
        finally:
            conn.close()

    def append(self, entry: LoggedDecision) -> LoggedDecision:
        with _AUDIT_WRITE_LOCK:
            conn = _get_connection(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                prev_row = conn.execute(
                    "SELECT record_hash FROM decisions ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                prev_hash = prev_row[0] if prev_row and prev_row[0] else ""

                payload: dict[str, Any] = {
                    "dispute_id": entry.dispute_id,
                    "reason_code": entry.reason_code,
                    "amount": float(entry.amount),
                    "win_probability": float(entry.win_probability),
                    "action": entry.action,
                    "reason": entry.reason,
                    "expected_value": float(entry.expected_value),
                    "evidence": entry.evidence,
                    "created_at": entry.created_at,
                    "model_version": entry.model_version,
                    "feature_version": entry.feature_version,
                    "policy_version": entry.policy_version,
                    "graph_data": entry.graph_data or {},
                    "ai_metadata": entry.ai_metadata or {},
                    "request_id": entry.request_id,
                    "routing_score": entry.routing_score,
                    "prev_hash": prev_hash,
                }
                if entry.payload_hash:
                    payload["payload_hash"] = entry.payload_hash
                if entry.actor and entry.actor != "anonymous":
                    payload["actor"] = entry.actor

                record_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()

                conn.execute(
                    """INSERT INTO decisions
                       (dispute_id, reason_code, amount, win_probability, action,
                        reason, expected_value, evidence_json, created_at,
                        model_version, feature_version, policy_version, graph_data_json,
                        ai_metadata_json, request_id, routing_score, prev_hash, record_hash,
                        payload_hash, actor)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.dispute_id,
                        entry.reason_code,
                        entry.amount,
                        entry.win_probability,
                        entry.action,
                        entry.reason,
                        entry.expected_value,
                        json.dumps(entry.evidence, sort_keys=True),
                        entry.created_at,
                        entry.model_version,
                        entry.feature_version,
                        entry.policy_version,
                        json.dumps(entry.graph_data or {}, sort_keys=True),
                        json.dumps(entry.ai_metadata or {}, sort_keys=True),
                        entry.request_id,
                        entry.routing_score,
                        prev_hash,
                        record_hash,
                        entry.payload_hash,
                        entry.actor or "anonymous",
                    ),
                )

                if entry.graph_data:
                    entity_rows = []
                    for field in ("customer_id", "device_id", "ip_address", "card_fingerprint"):
                        val = entry.graph_data.get(field)
                        if val not in (None, ""):
                            entity_rows.append(
                                (entry.dispute_id, field, str(val), float(entry.amount or 0.0))
                            )
                    if entity_rows:
                        conn.executemany(
                            "INSERT INTO graph_entities (dispute_id, entity_type, entity_value, amount) VALUES (?, ?, ?, ?)",
                            entity_rows,
                        )
                conn.commit()

                # Return populated entry
                entry.prev_hash = prev_hash
                entry.record_hash = record_hash
                entry.replayed = False
                return entry
            except sqlite3.IntegrityError:
                conn.rollback()
                existing = self.get(entry.dispute_id)
                if existing is None:
                    raise
                if (
                    entry.payload_hash
                    and existing.payload_hash
                    and existing.payload_hash != entry.payload_hash
                ):
                    raise PayloadConflictError(entry.dispute_id) from None
                return existing
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def verify(self) -> AuditVerificationResult:
        conn = _get_connection(self.db_path)
        try:
            rows = conn.execute("SELECT * FROM decisions ORDER BY rowid ASC").fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM decisions LIMIT 0").description]
            prev_hash = ""
            checked = 0
            for row in rows:
                rec = dict(zip(cols, row))
                expected_payload: dict[str, Any] = {
                    "dispute_id": rec["dispute_id"],
                    "reason_code": rec["reason_code"],
                    "amount": float(rec["amount"]),
                    "win_probability": float(rec["win_probability"]),
                    "action": rec["action"],
                    "reason": rec["reason"],
                    "expected_value": float(rec["expected_value"]),
                    "evidence": json.loads(rec["evidence_json"]),
                    "created_at": rec["created_at"],
                    "model_version": rec["model_version"],
                    "feature_version": rec["feature_version"],
                    "policy_version": rec["policy_version"],
                    "graph_data": json.loads(rec["graph_data_json"] or "{}"),
                    "ai_metadata": json.loads(rec.get("ai_metadata_json") or "{}"),
                    "request_id": rec.get("request_id", ""),
                    "routing_score": rec.get("routing_score"),
                    "prev_hash": rec.get("prev_hash", ""),
                }
                if rec.get("payload_hash"):
                    expected_payload["payload_hash"] = rec["payload_hash"]
                if rec.get("actor") and rec.get("actor") != "anonymous":
                    expected_payload["actor"] = rec["actor"]

                expected = hashlib.sha256(
                    json.dumps(expected_payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()

                if rec.get("prev_hash", "") != prev_hash or rec.get("record_hash", "") != expected:
                    return AuditVerificationResult(
                        valid=False,
                        checked=checked,
                        failed_dispute_id=rec["dispute_id"],
                        error="Hash chain verification mismatch",
                    )
                prev_hash = expected
                checked += 1
            return AuditVerificationResult(valid=True, checked=checked, head_hash=prev_hash)
        finally:
            conn.close()

    def export_head_anchor(self, secret_key: str | None = None) -> dict[str, Any]:
        """Export signed external anchor for off-site chain verification."""
        verification = self.verify()
        if not verification.valid:
            raise ValueError(
                f"Cannot export anchor for invalid audit log: {verification.failed_dispute_id}"
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        payload = f"{verification.head_hash}:{verification.checked}:{timestamp}"
        key = (
            secret_key or os.getenv("CHARGEBACK_ANCHOR_SECRET") or "default_anchor_signing_key"
        ).encode("utf-8")
        signature = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

        return {
            "timestamp": timestamp,
            "head_hash": verification.head_hash,
            "row_count": verification.checked,
            "signature": signature,
        }


def get_existing_decision(dispute_id: str, db_path: str = DB_PATH) -> LoggedDecision | None:
    return SQLiteAuditStore(db_path).get(dispute_id)


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
    routing_score: float | None = None,
    payload_hash: str = "",
    actor: str = "anonymous",
) -> LoggedDecision:
    store = SQLiteAuditStore(db_path)
    entry = LoggedDecision(
        dispute_id=dispute_id,
        reason_code=reason_code,
        amount=amount,
        win_probability=win_probability,
        action=action,
        reason=reason,
        expected_value=expected_value,
        evidence=evidence,
        created_at=datetime.now(timezone.utc).isoformat(),
        model_version=model_version,
        feature_version=feature_version,
        policy_version=policy_version,
        graph_data=graph_data or {},
        ai_metadata=ai_metadata or {},
        request_id=request_id,
        routing_score=routing_score,
        payload_hash=payload_hash,
        actor=actor,
    )
    return store.append(entry)


def verify_audit_integrity(db_path: str = DB_PATH) -> dict[str, Any]:
    res = SQLiteAuditStore(db_path).verify()
    result: dict[str, Any] = {
        "valid": res.valid,
        "checked": res.checked,
        "head_hash": res.head_hash,
    }
    if not res.valid:
        result["failed_dispute_id"] = res.failed_dispute_id
        if res.error:
            result["error"] = res.error
    return result


def export_head_anchor(db_path: str = DB_PATH, secret_key: str | None = None) -> dict[str, Any]:
    return SQLiteAuditStore(db_path).export_head_anchor(secret_key)


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
    routing_score: float | None = None,
    payload_hash: str = "",
    actor: str = "anonymous",
) -> LoggedDecision:
    store = SQLiteAuditStore(db_path)
    existing = store.get(dispute_id)
    if existing is not None:
        if payload_hash and existing.payload_hash and existing.payload_hash != payload_hash:
            raise PayloadConflictError(dispute_id)
        return existing

    computed = compute_decision_fn()
    if len(computed) == 5:
        win_probability, evidence, action, reason, expected_value = computed
        graph_data = {}
        ai_metadata = ai_metadata or None
        routing_score = routing_score
    elif len(computed) == 6:
        win_probability, evidence, action, reason, expected_value, graph_data = computed
        ai_metadata = None
        routing_score = routing_score
    elif len(computed) >= 7:
        (
            win_probability,
            evidence,
            action,
            reason,
            expected_value,
            graph_data,
            ai_metadata,
            *extra,
        ) = computed
        routing_score = extra[0] if extra else None
    else:
        raise ValueError("compute_decision_fn must return at least 5 values")

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
        routing_score=routing_score,
        payload_hash=payload_hash,
        actor=actor,
    )


def load_graph_rows(db_path: str = DB_PATH, dispute: dict | None = None) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        if dispute is None:
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

        target_entities = []
        for field in ("customer_id", "device_id", "ip_address", "card_fingerprint"):
            val = dispute.get(field)
            if val not in (None, ""):
                target_entities.append((field, str(val)))

        if not target_entities:
            return []

        placeholders = " OR ".join(
            ["(entity_type = ? AND entity_value = ?)"] * len(target_entities)
        )
        flat_params = [item for pair in target_entities for item in pair]

        query = f"""
            WITH hop1_disputes AS (
                SELECT DISTINCT dispute_id
                FROM graph_entities
                WHERE {placeholders}
            ),
            hop1_entities AS (
                SELECT g.entity_type, g.entity_value
                FROM graph_entities g
                JOIN hop1_disputes d ON g.dispute_id = d.dispute_id
                GROUP BY g.entity_type, g.entity_value
                HAVING COUNT(DISTINCT g.dispute_id) <= 20
            ),
            hop2_disputes AS (
                SELECT DISTINCT g.dispute_id
                FROM graph_entities g
                JOIN hop1_entities e ON g.entity_type = e.entity_type AND g.entity_value = e.entity_value
            ),
            hop2_entities AS (
                SELECT g.entity_type, g.entity_value
                FROM graph_entities g
                JOIN hop2_disputes d ON g.dispute_id = d.dispute_id
                GROUP BY g.entity_type, g.entity_value
                HAVING COUNT(DISTINCT g.dispute_id) <= 20
            ),
            relevant_disputes AS (
                SELECT DISTINCT g.dispute_id
                FROM graph_entities g
                JOIN hop2_entities e ON g.entity_type = e.entity_type AND g.entity_value = e.entity_value
                UNION
                SELECT dispute_id FROM hop2_disputes
                UNION
                SELECT dispute_id FROM hop1_disputes
            )
            SELECT d.dispute_id, d.amount, d.graph_data_json
            FROM decisions d
            JOIN relevant_disputes r ON d.dispute_id = r.dispute_id
        """
        cursor = conn.execute(query, flat_params)
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
