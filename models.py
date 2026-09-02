"""
models.py — the Dispute dataclass: the single data contract used
everywhere in this project (generator, scorer, policy, API).
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Dispute:
    # --- Core identifiers (field names mirror a typical payments dispute
    # API shape -- this is a demonstration layer, not the foundation) ---
    dispute_id: str
    payment_id: str
    reason_code: str
    amount: float
    respond_by: date

    # --- Evidence fields: every one is bool | None.
    # True = confirmed present, False = confirmed absent, None = unknown/
    # not collected. Collapsing None into False would silently corrupt
    # the signal, so this distinction is kept explicit everywhere.
    has_tracking_number: bool | None = None
    has_delivery_confirmation: bool | None = None
    has_signature_confirmation: bool | None = None

    has_product_photos: bool | None = None
    has_item_description_match: bool | None = None
    has_return_communication: bool | None = None

    has_avs_match: bool | None = None
    has_cvv_match: bool | None = None
    has_device_fingerprint_match: bool | None = None

    has_duplicate_transaction_proof: bool | None = None
    has_refund_already_issued: bool | None = None

    # --- Label (only present in training/eval data -- the real API request
    # a scorer receives at inference time will NOT include this field) ---
    would_win: bool | None = field(default=None)
