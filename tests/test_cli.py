"""Unit and integration tests for the unified chargeback-cli entrypoint."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from chargeback_risk_engine.cli import main


class TestCLI:
    """Verifies each subcommand of chargeback-cli."""

    def test_cli_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Unified management and operational CLI" in captured.out
        assert "verify-audit" in captured.out
        assert "evaluate" in captured.out

    def test_cli_no_args_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code in (0, 2)
        captured = capsys.readouterr()
        assert "chargeback-cli" in (captured.out + captured.err)

    def test_cli_verify_audit(self, tmp_path, capsys):
        db_path = str(tmp_path / "audit.db")
        from chargeback_risk_engine.audit_log import LoggedDecision, SQLiteAuditStore

        store = SQLiteAuditStore(db_path)
        store.append(
            LoggedDecision(
                dispute_id="CLI_DISP_001",
                reason_code="FRAUD",
                amount=1500.0,
                win_probability=0.5,
                action="HUMAN-REVIEW",
                reason="Test reason",
                expected_value=123.0,
                evidence=[],
                created_at="2026-10-31T00:00:00Z",
                actor="test_runner",
            )
        )

        ret = main(["verify-audit", "--db", db_path])
        assert ret == 0
        captured = capsys.readouterr()
        res = json.loads(captured.out)
        assert res["valid"] is True
        assert res["checked"] == 1
        assert len(res["head_hash"]) == 64

    def test_cli_evaluate(self, capsys):
        ret = main(["evaluate", "--csv", "data/sample_external_disputes.csv"])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_disputes"] == 10
        assert "operational_distribution" in data
        assert "HUMAN-REVIEW" in data["operational_distribution"]

    def test_cli_train_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["train", "--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--train-csv" in captured.out
        assert "--out" in captured.out

    @patch("uvicorn.run")
    def test_cli_serve(self, mock_uvicorn):
        ret = main(["serve", "--port", "8999", "--host", "127.0.0.1"])
        assert ret == 0
        mock_uvicorn.assert_called_once()
