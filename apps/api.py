"""Thin entry point for ``uvicorn apps.api:app``.

The canonical FastAPI implementation lives in ``chargeback_risk_engine.api``.
This module re-exports that single application and adds the audit-integrity
inspection endpoint without duplicating decision logic.
"""

from chargeback_risk_engine.api import app
from chargeback_risk_engine.audit_log import DB_PATH, verify_audit_integrity


@app.get("/audit/verify")
def audit_verify():
    """Verify the durable SQLite audit hash chain."""
    return verify_audit_integrity(DB_PATH)
