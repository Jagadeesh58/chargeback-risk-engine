"""Targeted test coverage completion for models, independent verifier, evidence, policy, and audit log."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pytest

from chargeback_risk_engine.audit_log import (
    LoggedDecision,
    SQLiteAuditStore,
    export_head_anchor,
    get_or_create_decision,
    load_graph_rows,
    verify_audit_integrity,
)
from chargeback_risk_engine.engine.evidence_score import score_evidence, validate_evidence_timestamp
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.independent_verifier import verify_decision
from chargeback_risk_engine.models import Dispute
from chargeback_risk_engine.policy import HUMAN_REVIEW, decide


class TestModelsAndVerifier:
    def test_dispute_dataclass(self):
        d = Dispute(
            dispute_id="D_TEST",
            payment_id="P_TEST",
            reason_code="fraud",
            amount=1500.0,
            respond_by=date(2026, 12, 1),
            customer_id="C01",
            device_id="DEV01",
            has_tracking_number=True,
            would_win=True,
        )
        assert d.dispute_id == "D_TEST"
        assert d.has_tracking_number is True
        assert d.has_delivery_confirmation is None
        assert d.would_win is True

    def test_independent_verifier_valid(self):
        valid_result = {
            "dispute_id": "D1",
            "action": "AUTO-CONTEST",
            "win_probability": 0.85,
            "routing_score": 0.85,
            "amount": 2500.0,
            "economic_decision": {"expected_net_value": 1500.0},
            "evidence_score": {
                "confidence": 0.9,
                "completeness": 1.0,
                "validity": 1.0,
                "items": [{"field": "has_tracking_number", "valid": True, "consistent": True}],
            },
            "graph_analysis": {"risk_score": 0.1, "cluster_size": 1},
        }
        res = verify_decision(valid_result)
        assert res["valid"] is True
        assert not res["errors"]

    def test_independent_verifier_missing_fields(self):
        res = verify_decision({"dispute_id": "D1"})
        assert res["valid"] is False
        assert any("missing:" in e for e in res["errors"])

    def test_independent_verifier_invalid_values(self):
        invalid_result = {
            "dispute_id": "D1",
            "action": "INVALID_ACTION",
            "win_probability": 1.5,
            "routing_score": -0.2,
            "amount": -50.0,
            "economic_decision": {"expected_net_value": -100.0},
            "evidence_score": {"confidence": 0.1, "completeness": 0.1, "items": []},
            "graph_analysis": {"risk_score": 0.9, "cluster_size": 10},
        }
        res = verify_decision(invalid_result)
        assert res["valid"] is False
        assert "invalid_action" in res["errors"]
        assert "invalid_probability" in res["errors"]
        assert "invalid_routing_score" in res["errors"]
        assert "invalid_amount" in res["errors"]

    def test_independent_verifier_auto_contest_violations(self):
        violating = {
            "dispute_id": "D1",
            "action": "AUTO-CONTEST",
            "win_probability": 0.50,
            "routing_score": 0.50,
            "amount": 60000.0,  # Above 50,000 ceiling
            "economic_decision": {"expected_net_value": -10.0},  # Negative EV
            "evidence_score": {
                "confidence": 0.4,
                "completeness": 0.4,
                "validity": 0.5,
                "items": [{"valid": False, "consistent": False}],
            },
            "graph_analysis": {"risk_score": 0.8, "cluster_size": 10},
        }
        res = verify_decision(violating)
        assert res["valid"] is False
        assert "ceiling_bypass" in res["errors"]
        assert "incomplete_evidence_auto_contest" in res["errors"]
        assert "invalid_evidence_auto_contest" in res["errors"]
        assert "graph_escalation_bypass" in res["errors"]
        assert "negative_economics_auto_contest" in res["errors"]


class TestEvidenceScoreEdgeCases:
    def test_invalid_and_edge_timestamps(self, monkeypatch):
        assert not validate_evidence_timestamp("not-a-valid-timestamp-format")

        # Naive ISO timestamp without timezone
        assert validate_evidence_timestamp("2026-10-30T12:00:00")

        # Future timestamp (> 300s)
        assert not validate_evidence_timestamp("2099-01-01T00:00:00Z")

        # Too old timestamp (> 365 days)
        assert not validate_evidence_timestamp("2020-01-01T00:00:00Z")

        # Corrupted non-float max age env var
        monkeypatch.setenv("CHARGEBACK_MAX_EVIDENCE_AGE_DAYS", "invalid-number")
        assert validate_evidence_timestamp(datetime.now(timezone.utc).isoformat())

    def test_score_evidence_with_meta_objects(self):
        class PydanticV2Meta:
            def model_dump(self):
                return {
                    "source": "carrier_api",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        class PydanticV1Meta:
            def dict(self):
                return {
                    "source": "gateway_api",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        dispute = {
            "reason_code": "item_not_received",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
            "evidence_source_reliability": "invalid_float",  # triggers ValueError branch
            "evidence_meta": {
                "has_tracking_number": PydanticV2Meta(),
                "has_delivery_confirmation": PydanticV1Meta(),
                "has_signature_confirmation": 12345,  # non-dict branch
            },
        }
        packet = assemble(dispute)
        score = score_evidence(dispute, packet)
        assert score.completeness == 1.0

    def test_score_evidence_valid_source_reliability(self):
        dispute = {
            "reason_code": "item_not_received",
            "has_tracking_number": True,
            "has_delivery_confirmation": True,
            "has_signature_confirmation": True,
            "evidence_source_reliability": 0.85,
        }
        packet = assemble(dispute)
        score = score_evidence(dispute, packet)
        assert score.confidence > 0.8
        assert score.to_dict()["completeness"] == 1.0

    def test_load_graph_rows_targeted_dispute(self, tmp_path):
        db_path = str(tmp_path / "graph.db")
        store = SQLiteAuditStore(db_path)
        store.append(
            LoggedDecision(
                dispute_id="D_G1",
                reason_code="fraud",
                amount=1000.0,
                win_probability=0.8,
                action="HUMAN-REVIEW",
                reason="Review",
                expected_value=500.0,
                evidence=[],
                created_at="2026-10-31T00:00:00Z",
                graph_data={"customer_id": "cust_123"},
            )
        )
        rows = load_graph_rows(db_path, dispute={"customer_id": "cust_123"})
        assert len(rows) == 1


class TestPolicyRoutingScoreCoverage:
    def test_invalid_decision_score_fails_closed(self):
        # decision_score not finite or not in [0, 1]
        for bad_score in [-0.01, 1.01, float("nan"), float("inf")]:
            dec = decide(win_probability=0.8, amount=1000.0, decision_score=bad_score)
            assert dec.action == HUMAN_REVIEW
            assert "Invalid deterministic routing score" in dec.reason

    def test_evidence_quality_gates_fail_closed(self):
        from dataclasses import dataclass

        @dataclass
        class Item:
            valid: bool
            consistent: bool

        @dataclass
        class IncompleteQuality:
            completeness: float
            items: list[Item]

        # Completeness gate
        low_comp = IncompleteQuality(completeness=0.2, items=[])
        d1 = decide(0.8, 1000.0, evidence_quality=low_comp)
        assert d1.action == HUMAN_REVIEW
        assert "below required" in d1.reason

        # Invalid/contradictory gate
        bad_quality = IncompleteQuality(
            completeness=1.0, items=[Item(valid=False, consistent=True)]
        )
        d2 = decide(0.8, 1000.0, evidence_quality=bad_quality)
        assert d2.action == HUMAN_REVIEW
        assert "Evidence quality failed" in d2.reason


class TestAuditLogCoverage:
    def test_load_graph_rows_bulk_and_corrupted(self, tmp_path):
        db_path = str(tmp_path / "audit.db")
        store = SQLiteAuditStore(db_path)
        store.append(
            LoggedDecision(
                dispute_id="D_BULK_1",
                reason_code="fraud",
                amount=1200.0,
                win_probability=0.7,
                action="HUMAN-REVIEW",
                reason="Review",
                expected_value=500.0,
                evidence=[],
                created_at="2026-10-31T00:00:00Z",
                graph_data={"device_id": "dev123"},
            )
        )

        # Dispute=None loads all graph rows
        rows = load_graph_rows(db_path, dispute=None)
        assert len(rows) == 1
        assert rows[0]["device_id"] == "dev123"

        # Corrupt graph_data_json in DB directly
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE decisions SET graph_data_json = '{corrupted json' WHERE dispute_id = 'D_BULK_1'"
        )
        conn.commit()
        conn.close()

        corrupted_rows = load_graph_rows(db_path, dispute=None)
        assert len(corrupted_rows) == 1
        assert corrupted_rows[0]["dispute_id"] == "D_BULK_1"

    def test_export_head_anchor_and_verify_error(self, tmp_path):
        db_path = str(tmp_path / "anchor.db")
        store = SQLiteAuditStore(db_path)
        store.append(
            LoggedDecision(
                dispute_id="D_ANCHOR_1",
                reason_code="fraud",
                amount=1200.0,
                win_probability=0.7,
                action="HUMAN-REVIEW",
                reason="Review",
                expected_value=500.0,
                evidence=[],
                created_at="2026-10-31T00:00:00Z",
            )
        )
        anchor = export_head_anchor(db_path=db_path, secret_key="secret123")
        assert "head_hash" in anchor
        assert "signature" in anchor

        # Tamper with record_hash to trigger verification failure error branch
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE decisions SET record_hash = 'tampered' WHERE dispute_id = 'D_ANCHOR_1'"
        )
        conn.commit()
        conn.close()

        res = verify_audit_integrity(db_path=db_path)
        assert res["valid"] is False
        assert "failed_dispute_id" in res

    def test_get_or_create_decision_variant_signatures(self, tmp_path):
        db_path = str(tmp_path / "variants.db")

        # 6-tuple return
        d6 = get_or_create_decision(
            dispute_id="D_VAR_6",
            reason_code="fraud",
            amount=1000.0,
            compute_decision_fn=lambda: (
                0.7,
                [],
                "HUMAN-REVIEW",
                "reason",
                200.0,
                {"device_id": "d6"},
            ),
            db_path=db_path,
        )
        assert d6.dispute_id == "D_VAR_6"

        # Invalid < 5 return raises ValueError
        with pytest.raises(ValueError, match="compute_decision_fn must return at least 5 values"):
            get_or_create_decision(
                dispute_id="D_VAR_BAD",
                reason_code="fraud",
                amount=1000.0,
                compute_decision_fn=lambda: (0.7, [], "HUMAN-REVIEW"),
                db_path=db_path,
            )
