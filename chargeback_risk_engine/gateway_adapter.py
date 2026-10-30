"""
payment-gateway adapter — translates between this project's internal
 dispute/evidence shapes and a generic payment‑gateway dispute API shape, enabling
 integration without vendor lock‑in. The adapter provides mock request/response
 structures suitable for demo and testing; no network calls or credentials are used.

Field mappings are defined generically; the adapter produces a draft payload
 for contesting disputes. The `action` field is always "draft" in the automatic
 pipeline, preserving safety by preventing unintended submissions.
"""

import hashlib

from chargeback_risk_engine.paths import DATA_DIR
from datetime import datetime, timedelta, timezone

# Mapping from internal evidence fields to generic payment‑gateway evidence categories.
# Categories are generic across reason codes (shipping_proof, billing_proof, ...).
# This mapping is based on domain knowledge and does not rely on any vendor documentation.
# Fields without a clear match fall back to "others".
EVIDENCE_FIELD_TO_GATEWAY_CATEGORY = {
    "has_tracking_number": "shipping_proof",
    "has_delivery_confirmation": "shipping_proof",
    "has_signature_confirmation": "shipping_proof",
    "has_return_communication": "customer_communication",
    "has_device_fingerprint_match": "access_activity_log",
    "has_duplicate_transaction_proof": "billing_proof",
    "has_refund_already_issued": "refund_confirmation",
}

GATEWAY_EVIDENCE_CATEGORIES = (
    "shipping_proof", "billing_proof", "cancellation_proof",
    "customer_communication", "proof_of_service", "explanation_letter",
    "refund_confirmation", "access_activity_log",
    "refund_cancellation_policy", "term_and_conditions",
)


def _mock_document_id(dispute_id: str, field_name: str) -> str:
    """Deterministic, not random -- the same dispute_id + field always
    produces the same mock document ID. This matters because
    generate_contest_draft() is called fresh on every request rather
    than stored in the audit log; if the IDs were random, a replayed
    decision (audit_log.py's idempotency guarantee) would come back
    with a different draft each time, which would break that
    guarantee's whole point."""
    digest = hashlib.sha1(f"{dispute_id}:{field_name}".encode()).hexdigest()[:8]
    return f"doc_MOCK{digest}"


# IMPORTANT: this adapter is intentionally local/mock.
# It never uses gateway credentials or performs a network request.

def fetch_dispute(dispute_id: str, csv_path: str | None = None) -> dict:
    """
    Stands in for GET /v1/disputes/:id. A real integration would call
    that endpoint on the payment gateway's servers and get back a JSON object
    shaped like the one this function returns; this mock looks the
    dispute up in our own synthetic dataset instead, so the whole
    pipeline can be exercised with zero gateway credentials.

    Note: a real payment-gateway dispute entity would not typically include the
    has_tracking_number-style evidence fields returned here -- those
    come from the merchant's own systems, not from the gateway. They're
    bundled in below only because that's how this project's synthetic
    dataset happens to store everything in one row.
    """
    import csv

    if csv_path is None:
        csv_path = str(DATA_DIR / "test.csv")
    row = None
    with open(csv_path, newline="") as f:
        for candidate in csv.DictReader(f):
            if candidate["dispute_id"] == dispute_id:
                row = candidate
                break
    if row is None:
        raise KeyError(f"No dispute {dispute_id!r} found in {csv_path}")

    row["amount"] = float(row["amount"])
    for k, v in row.items():
        if v == "":
            row[k] = None
        elif v in ("True", "False"):
            row[k] = v == "True"

    respond_by = datetime.now(timezone.utc) + timedelta(days=7)
    evidence_fields = {
        k: v for k, v in row.items()
        if k not in ("dispute_id", "payment_id", "reason_code", "amount",
                     "respond_by", "would_win")
    }
    return {
        "id": f"disp_MOCK{dispute_id}",
        "entity": "dispute",
        "payment_id": f"pay_MOCK{dispute_id}",
        "amount": int(round(row["amount"] * 100)),  # amounts in minor units (e.g. paise/cents)
        "currency": "INR",
        "amount_deducted": int(round(row["amount"] * 100)),
        "reason_code": row["reason_code"],
        "reason_description": row["reason_code"].replace("_", " "),
        "respond_by": int(respond_by.timestamp()),
        "status": "open",
        "phase": "evidence_submission",
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "evidence": None,
        **evidence_fields,
    }


def gateway_dispute_to_internal_dict(gateway_dispute: dict) -> dict:
    """The inverse of fetch_dispute()'s shaping: takes a payment-gateway-shaped
    dispute (minor currency units, disp_/pay_ prefixed ids) and converts it into the
    plain dict scorer.py/evidence.py/policy.py already expect."""
    internal = dict(gateway_dispute)
    internal["dispute_id"] = gateway_dispute["id"].removeprefix("disp_MOCK")
    internal["payment_id"] = gateway_dispute["payment_id"]
    internal["amount"] = gateway_dispute["amount"] / 100.0  # minor units -> major units
    return internal


def build_contest_payload(dispute_id: str, amount: float, evidence_items: list[dict],
                            summary: str, action: str = "draft") -> dict:
    """
    Builds the dispute contest request body for the payment gateway API.
    `action` mirrors standard gateway fields of the same name ("draft" | "submit").
    Nothing here calls a network endpoint regardless of the value -- this only shapes a dict.
    """
    if action not in ("draft", "submit"):
        raise ValueError(f"action must be 'draft' or 'submit', got {action!r}")

    payload = {category: [] for category in GATEWAY_EVIDENCE_CATEGORIES}
    others = []

    for item in evidence_items:
        if item["status"] != "PASS":
            continue  # never attach evidence that wasn't confirmed present
        category = EVIDENCE_FIELD_TO_GATEWAY_CATEGORY.get(item["field"], "others")
        doc_id = _mock_document_id(dispute_id, item["field"])
        if category == "others":
            others.append({"type": item["field"], "document_ids": [doc_id]})
        else:
            payload[category].append(doc_id)

    payload["others"] = others
    payload["amount"] = int(round(amount * 100))
    payload["summary"] = summary
    payload["action"] = action
    return payload


def generate_contest_draft(dispute_id: str, amount: float, evidence_items: list[dict],
                             summary: str) -> dict:
    """
    The only entry point the automatic pipeline calls. There is no
    parameter here that lets a caller ask for "submit" -- structurally
    the same way policy.py's monetary ceiling can't be argued around by
    a confident probability. A real submission would need a separate,
    explicitly human-triggered call outside this pipeline.
    """
    return build_contest_payload(dispute_id, amount, evidence_items, summary, action="draft")
