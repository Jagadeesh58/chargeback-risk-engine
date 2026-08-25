"""
test_evidence.py — real, runnable tests for evidence.py.
"""

from evidence import assemble
from config import RELEVANT_EVIDENCE_BY_REASON, REASON_CODES


def test_true_maps_to_pass():
    dispute = {"reason_code": "item_not_received", "has_tracking_number": True}
    packet = assemble(dispute)
    item = next(i for i in packet.items if i.field == "has_tracking_number")
    assert item.status == "PASS"


def test_false_maps_to_fail():
    dispute = {"reason_code": "item_not_received", "has_tracking_number": False}
    packet = assemble(dispute)
    item = next(i for i in packet.items if i.field == "has_tracking_number")
    assert item.status == "FAIL"


def test_none_maps_to_warn_never_pass():
    """Core principle #10 requirement: unknown evidence must never be
    fabricated as PASS."""
    dispute = {"reason_code": "item_not_received", "has_tracking_number": None}
    packet = assemble(dispute)
    item = next(i for i in packet.items if i.field == "has_tracking_number")
    assert item.status == "WARN"
    assert item.status != "PASS"


def test_missing_key_also_maps_to_warn():
    """A field not present in the dict at all (not even as None) should
    also be treated as unknown, not fabricated as PASS."""
    dispute = {"reason_code": "item_not_received"}  # no evidence fields at all
    packet = assemble(dispute)
    assert all(i.status == "WARN" for i in packet.items)


def test_packet_only_contains_relevant_fields():
    """The packet for a given reason_code should only ever contain that
    reason's relevant fields, not fields from other reason codes."""
    for reason in REASON_CODES:
        dispute = {"reason_code": reason}
        packet = assemble(dispute)
        packet_fields = {i.field for i in packet.items}
        assert packet_fields == set(RELEVANT_EVIDENCE_BY_REASON[reason])


def test_counts_are_consistent():
    dispute = {
        "reason_code": "item_not_received",
        "has_tracking_number": True,
        "has_delivery_confirmation": False,
        "has_signature_confirmation": None,
    }
    packet = assemble(dispute)
    assert packet.pass_count == 1
    assert packet.fail_count == 1
    assert packet.warn_count == 1
    assert packet.total == 3