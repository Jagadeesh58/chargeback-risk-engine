"""
test_razorpay_adapter.py — real, runnable tests for razorpay_adapter.py.
"""

import csv

import pytest

from chargeback_risk_engine.razorpay_adapter import (
    build_contest_payload,
    fetch_dispute,
    generate_contest_draft,
    razorpay_dispute_to_internal_dict,
)


def _a_real_dispute_id_from(csv_path="data/test.csv"):
    with open(csv_path, newline="") as f:
        return next(csv.DictReader(f))["dispute_id"]


def test_only_pass_evidence_is_attached():
    evidence_items = [
        {"field": "has_tracking_number", "status": "PASS"},
        {"field": "has_delivery_confirmation", "status": "WARN"},
        {"field": "has_signature_confirmation", "status": "FAIL"},
    ]
    draft = generate_contest_draft("D1", 1000.0, evidence_items, "summary")
    assert len(draft["shipping_proof"]) == 1
    assert draft["billing_proof"] == []


def test_unmapped_field_falls_back_to_others():
    evidence_items = [{"field": "has_product_photos", "status": "PASS"}]
    draft = generate_contest_draft("D1", 1000.0, evidence_items, "summary")
    assert len(draft["others"]) == 1
    assert draft["others"][0]["type"] == "has_product_photos"
    assert len(draft["others"][0]["document_ids"]) == 1


def test_amount_converted_to_paise():
    draft = generate_contest_draft("D1", 1234.56, [], "summary")
    assert draft["amount"] == 123456


def test_draft_is_deterministic_for_idempotent_replay():
    evidence_items = [{"field": "has_tracking_number", "status": "PASS"}]
    draft_a = generate_contest_draft("D_SAME", 500.0, evidence_items, "s")
    draft_b = generate_contest_draft("D_SAME", 500.0, evidence_items, "s")
    assert draft_a == draft_b


def test_different_dispute_ids_get_different_document_ids():
    evidence_items = [{"field": "has_tracking_number", "status": "PASS"}]
    draft_a = generate_contest_draft("D_A", 500.0, evidence_items, "s")
    draft_b = generate_contest_draft("D_B", 500.0, evidence_items, "s")
    assert draft_a["shipping_proof"] != draft_b["shipping_proof"]


def test_generate_contest_draft_has_no_way_to_request_submit():
    """Structural check: the function the automatic pipeline calls
    doesn't expose an `action` parameter at all, so it's impossible for
    a caller to accidentally produce a "submit" payload through it."""
    import inspect
    sig = inspect.signature(generate_contest_draft)
    assert "action" not in sig.parameters


def test_generate_contest_draft_always_says_draft():
    draft = generate_contest_draft("D1", 100.0, [], "s")
    assert draft["action"] == "draft"


def test_build_contest_payload_rejects_invalid_action():
    try:
        build_contest_payload("D1", 100.0, [], "s", action="not_a_real_action")
        assert False, "should have raised"
    except ValueError:
        pass


def test_build_contest_payload_supports_explicit_submit():
    """submit is a real, valid shape for a real integration to use later
    -- just never produced by generate_contest_draft(), which is the
    only function the automatic pipeline calls."""
    payload = build_contest_payload("D1", 100.0, [], "s", action="submit")
    assert payload["action"] == "submit"


def test_razorpay_dispute_to_internal_dict_round_trips_amount():
    rp_dispute = {
        "id": "disp_MOCKD0001",
        "payment_id": "pay_MOCKD0001",
        "amount": 200000,
        "reason_code": "item_not_received",
    }
    internal = razorpay_dispute_to_internal_dict(rp_dispute)
    assert internal["dispute_id"] == "D0001"
    assert internal["amount"] == 2000.0


def test_fetch_dispute_matches_real_csv_row():
    dispute_id = _a_real_dispute_id_from()
    with open("data/test.csv", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["dispute_id"] == dispute_id)

    rp_dispute = fetch_dispute(dispute_id)
    assert rp_dispute["id"] == f"disp_MOCK{dispute_id}"
    assert rp_dispute["reason_code"] == row["reason_code"]
    assert rp_dispute["amount"] == int(round(float(row["amount"]) * 100))
    assert rp_dispute["currency"] == "INR"


def test_fetch_dispute_round_trips_through_internal_dict():
    dispute_id = _a_real_dispute_id_from()
    with open("data/test.csv", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["dispute_id"] == dispute_id)

    rp_dispute = fetch_dispute(dispute_id)
    internal = razorpay_dispute_to_internal_dict(rp_dispute)
    assert internal["dispute_id"] == dispute_id
    assert internal["amount"] == pytest.approx(float(row["amount"]))


def test_fetch_dispute_unknown_id_raises():
    with pytest.raises(KeyError):
        fetch_dispute("D_NOT_A_REAL_DISPUTE_ID")
