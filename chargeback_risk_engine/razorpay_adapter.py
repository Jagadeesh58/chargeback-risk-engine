"""
razorpay_adapter.py — translates between this project's internal
dispute/evidence shapes and Razorpay's real Disputes API shapes, so the
evidence this system assembles could plug into a real integration later
without changing scorer.py/evidence.py/policy.py at all.

The field names below mirror Razorpay's public Disputes API
(razorpay.com/docs/api/disputes), specifically the dispute entity
(id, payment_id, amount, currency, reason_code, respond_by, status,
phase) and the PATCH /v1/disputes/:id/contest endpoint's request body
(amount, summary, shipping_proof, billing_proof, cancellation_proof,
customer_communication, proof_of_service, explanation_letter,
refund_confirmation, access_activity_log, refund_cancellation_policy,
term_and_conditions, others, action). That endpoint's own "action"
field takes "draft" or "submit" -- this project only ever produces
"draft".

There is no code here that actually calls Razorpay's servers. This
project has zero Razorpay credentials, and an autonomous system
shouldn't auto-submit real evidence to a real dispute without a human
in the loop anyway, so a live-submission path would be both unverified
and against the project's own safety stance. Everything below is a
mock: it produces exactly the request/response shapes a real
integration would use, so the pipeline's output is realistic and
swappable later, without ever making a network call.
"""

import hashlib

from chargeback_risk_engine.paths import DATA_DIR
from datetime import datetime, timedelta, timezone

# Best-effort mapping from this project's evidence fields to Razorpay's
# evidence categories. Razorpay's categories are generic across reason
# codes (shipping_proof, billing_proof, ...), not specific to the 4
# reason codes this project uses, so this mapping is my own judgment
# call about the closest match for each field -- not something
# Razorpay documents directly. Anything without an obvious match falls
# back to "others".
EVIDENCE_FIELD_TO_RAZORPAY_CATEGORY = {
    "has_tracking_number": "shipping_proof",
    "has_delivery_confirmation": "shipping_proof",
    "has_signature_confirmation": "shipping_proof",
    "has_return_communication": "customer_communication",
    "has_device_fingerprint_match": "access_activity_log",
    "has_duplicate_transaction_proof": "billing_proof",
    "has_refund_already_issued": "refund_confirmation",
}

RAZORPAY_EVIDENCE_CATEGORIES = (
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


def fetch_dispute(dispute_id: str, csv_path: str | None = None) -> dict:
    """
    Stands in for GET /v1/disputes/:id. A real integration would call
    that endpoint on Razorpay's servers and get back a JSON object
    shaped like the one this function returns; this mock looks the
    dispute up in our own synthetic dataset instead, so the whole
    pipeline can be exercised with zero Razorpay credentials.

    Note: a real Razorpay dispute entity would NOT include the
    has_tracking_number-style evidence fields returned here -- those
    come from the merchant's own systems, not from Razorpay. They're
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
        "amount": int(round(row["amount"] * 100)),  # Razorpay amounts are in paise
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


def razorpay_dispute_to_internal_dict(rp_dispute: dict) -> dict:
    """The inverse of fetch_dispute()'s shaping: takes a Razorpay-shaped
    dispute (paise, disp_/pay_ prefixed ids) and converts it into the
    plain dict scorer.py/evidence.py/policy.py already expect."""
    internal = dict(rp_dispute)
    internal["dispute_id"] = rp_dispute["id"].removeprefix("disp_MOCK")
    internal["payment_id"] = rp_dispute["payment_id"]
    internal["amount"] = rp_dispute["amount"] / 100.0  # paise -> rupees
    return internal


def build_contest_payload(dispute_id: str, amount: float, evidence_items: list[dict],
                            summary: str, action: str = "draft") -> dict:
    """
    Builds the exact request body PATCH /v1/disputes/:id/contest would
    take on the real API. `action` mirrors Razorpay's own field of the
    same name ("draft" | "submit"). Nothing here calls a network
    endpoint regardless of the value -- this only shapes a dict.
    """
    if action not in ("draft", "submit"):
        raise ValueError(f"action must be 'draft' or 'submit', got {action!r}")

    payload = {category: [] for category in RAZORPAY_EVIDENCE_CATEGORIES}
    others = []

    for item in evidence_items:
        if item["status"] != "PASS":
            continue  # never attach evidence that wasn't confirmed present
        category = EVIDENCE_FIELD_TO_RAZORPAY_CATEGORY.get(item["field"], "others")
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
