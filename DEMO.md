# Demo

## Start

```bash
pip install -r requirements.txt
streamlit run apps/app_deployed.py
```

Optional API:

```bash
uvicorn apps.api:app --reload
```

CLI demo:

```bash
python scripts/demo.py
```

## Core cases
- Strong evidence: item_not_received, ₹2,400, all three relevant evidence fields True -> AUTO-CONTEST.
- Missing evidence: tracking True, delivery/signature Unknown -> HUMAN REVIEW.
- Over ceiling: ₹725,000 with perfect evidence -> HUMAN REVIEW.

Use fresh dispute IDs to demonstrate idempotency correctly.


## Failure-path demo coverage
`python scripts/demo.py` now demonstrates:
- strong evidence -> AUTO-CONTEST (draft only)
- missing evidence -> HUMAN REVIEW
- amount above the safety ceiling -> HUMAN REVIEW
- contradictory evidence -> HUMAN REVIEW
- high shared-device/IP relationship risk -> HUMAN REVIEW
- duplicate dispute ID -> original persisted decision is replayed


## Note on the hosted demo

The audit trail (`audit_log.db`) is a local SQLite file. On Streamlit
Community Cloud, the filesystem is ephemeral — it resets on redeploys
and on wake-from-sleep. If the idempotent-replay demo (submitting the
same dispute_id twice) doesn't find an old dispute_id after a long
gap, that's this hosting limitation, not a logic bug. Locally, the
audit trail is fully persistent across restarts.
