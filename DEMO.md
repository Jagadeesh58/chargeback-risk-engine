# Demo

## Start

```bash
pip install -r requirements.txt
streamlit run app_deployed.py
```

Optional API:

```bash
uvicorn api:app --reload
```

CLI demo:

```bash
python demo.py
```

## Core cases
- Strong evidence: item_not_received, ₹2,400, all three relevant evidence fields True -> AUTO-CONTEST.
- Missing evidence: tracking True, delivery/signature Unknown -> HUMAN REVIEW.
- Over ceiling: ₹725,000 with perfect evidence -> HUMAN REVIEW.

Use fresh dispute IDs to demonstrate idempotency correctly.


## Failure-path demo coverage
`python demo.py` now demonstrates:
- strong evidence -> AUTO-CONTEST (draft only)
- missing evidence -> HUMAN REVIEW
- amount above the safety ceiling -> HUMAN REVIEW
- contradictory evidence -> HUMAN REVIEW
- high shared-device/IP relationship risk -> HUMAN REVIEW
- duplicate dispute ID -> original persisted decision is replayed
