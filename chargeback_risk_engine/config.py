"""Shared configuration for the chargeback decision engine."""

REASON_CODES = [
    "item_not_received",
    "item_not_as_described",
    "unauthorized_transaction",
    "duplicate_charge",
]

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

ALL_EVIDENCE_FIELDS = sorted(
    {field for fields in RELEVANT_EVIDENCE_BY_REASON.values() for field in fields}
)

# Kept for offline challenger evaluation only. The live path uses Logistic
# Regression as the single risk estimator.
HYBRID_MODEL_WEIGHTS = {"rules": 0.20, "logistic": 0.55, "tree": 0.25}

LIVE_MODEL_VERSION = "logreg-v1"
RULE_MODEL_VERSION = "rules-v1"
CHALLENGER_MODEL_VERSION = "hgb-v1"
MODEL_VERSION = LIVE_MODEL_VERSION
FEATURE_VERSION = "features-v3"
POLICY_VERSION = "policy-v5-dev-optimized"
GRAPH_HUMAN_REVIEW_THRESHOLD = 0.60
MIN_EVIDENCE_COMPLETENESS_FOR_AUTO = 0.50
MAX_EVIDENCE_INVALID_OR_CONTRADICTORY = 0
