"""
config.py — shared constants for the chargeback risk engine.

Four reason codes, each with evidence fields that are RELEVANT to that
specific reason. This matters later: evidence relevant to one reason code
should not be able to influence the score for a dispute filed under a
different reason code (enforced structurally in scorer.py).
"""

REASON_CODES = [
    "item_not_received",
    "item_not_as_described",
    "unauthorized_transaction",
    "duplicate_charge",
]

# Which evidence fields matter for each reason code.
# (Used by the scorer -- defined here so hidden_truth.py and the scorer
# share one source of truth for "what's relevant to what".)
RELEVANT_EVIDENCE_BY_REASON = {
    "item_not_received": [
        "has_tracking_number",
        "has_delivery_confirmation",
        "has_signature_confirmation",
    ],
    "item_not_as_described": [
        "has_product_photos",
        "has_item_description_match",
        "has_return_communication",
    ],
    "unauthorized_transaction": [
        "has_avs_match",
        "has_cvv_match",
        "has_device_fingerprint_match",
    ],
    "duplicate_charge": [
        "has_duplicate_transaction_proof",
        "has_refund_already_issued",
    ],
}

# Every evidence field that exists anywhere in the dataset, across all
# reason codes. A dispute filed under one reason code will still HAVE
# values for other reason codes' fields (that's realistic -- the system
# collects a standard form either way) but those values should be
# irrelevant to that dispute's score.
ALL_EVIDENCE_FIELDS = sorted(
    {field for fields in RELEVANT_EVIDENCE_BY_REASON.values() for field in fields}
)
