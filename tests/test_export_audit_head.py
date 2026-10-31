"""Tests for export_audit_head.py script."""
import os
import subprocess
import sys
import tempfile
import pytest

from chargeback_risk_engine.audit_log import log_new_decision
from scripts.export_audit_head import export_audit_head, verify_against_head


def test_export_and_verify_audit_head_flow():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test_audit.db")

        # Log two decisions
        log_new_decision("D_EXPORT_1", "item_not_received", 1000.0, 0.8, "AUTO-CONTEST", "test 1", 700.0, [], db_path=db_path)
        log_new_decision("D_EXPORT_2", "unauthorized_transaction", 2500.0, 0.2, "ACCEPT-LOSS", "test 2", -100.0, [], db_path=db_path)

        # Export head
        exported = export_audit_head(db_path=db_path)
        assert exported["status"] == "valid"
        assert exported["checked_records"] == 2
        assert len(exported["head_hash"]) == 64

        head_hash = exported["head_hash"]

        # Verify against expected head
        assert verify_against_head(head_hash, db_path=db_path) is True
        assert verify_against_head("0" * 64, db_path=db_path) is False

        # Test CLI invocation
        res = subprocess.run(
            [sys.executable, "scripts/export_audit_head.py", "--db", db_path, "--verify", "--against", head_hash],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "SUCCESS" in res.stdout

        res_bad = subprocess.run(
            [sys.executable, "scripts/export_audit_head.py", "--db", db_path, "--verify", "--against", "bad_hash"],
            capture_output=True,
            text=True,
        )
        assert res_bad.returncode == 1
