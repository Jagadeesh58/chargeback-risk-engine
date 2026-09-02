# Chargeback Risk Engine

Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager.

A scoring + policy pipeline for payment disputes (chargebacks): given a
disputed transaction and whatever evidence has been collected about it,
the system estimates the probability a contest would win, applies a
deterministic safety policy on top of that estimate, and — only when the
policy says to contest — produces a ready-to-review draft evidence
submission. Every decision, honest or not, is measured against a
held-out test set and logged.

**This is not an agent.** It never browses, chats, negotiates, or acts on
its own initiative. It takes one dispute in, and returns one decision
out: `AUTO-CONTEST`, `HUMAN REVIEW`, or `ACCEPT LOSS`. Nothing it produces
is ever submitted anywhere automatically — see the trust boundary table
below.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram, color-coded
against the trust boundary below. Quick version:

```
generate_data.py / hidden_truth.py        (synthetic dispute data, held-out train/dev/test split)
            |
            v
scorer.py            -- rule-based, reason-code-aware P(win) estimate
            |
            v
evidence.py          -- PASS / WARN / FAIL packet for the relevant fields
            |
            v
policy.py            -- monetary ceiling (unconditional) + evidence gate
            |          -> AUTO-CONTEST | HUMAN REVIEW | ACCEPT LOSS
            v
audit_log.py         -- SQLite, one row per dispute_id, idempotent replay
            |
            v
calibration.py       -- corrects the raw P(win) against real outcomes on
                         dev.csv (isotonic regression); informational only,
                         does NOT feed back into the decision above
            |
            v
razorpay_adapter.py  -- (only if AUTO-CONTEST) draft evidence submission
                         in Razorpay's real API shape -- never submitted
            |
            v
api.py (FastAPI)  <---calls--- app.py / app_deployed.py (Streamlit)
```

`api.py` and `app.py`/`app_deployed.py` contain no scoring or policy
logic of their own — they only call the modules above and format the
result. `ml_scorer.py` is an alternate, optional scorer kept for
comparison; `policy.py` never calls it. `metrics.py`, `baseline.py`, and
`sensitivity.py` evaluate the pipeline after the fact — they don't feed
back into it. `calibration.py` is similar: it corrects the probability
*shown*, never the probability the routing decision was made from.

## Trust boundary

What's allowed to act on its own, and what isn't:

| Component | Autonomous? | Why it's safe to let it act (or why it can't) |
|---|---|---|
| `scorer.py` (P(win) estimate) | Advisory only | Produces a number; never takes an action itself |
| Monetary ceiling (`policy.py`) | Yes, unconditionally | Checked first, structurally can't read `win_probability` — proven by a 2000-case fuzz test |
| Evidence-completeness gate (`policy.py`) | Yes | Blocks `AUTO-CONTEST` unless a majority of relevant evidence is confirmed `PASS`, regardless of probability |
| `AUTO-CONTEST` decision | Yes, but bounded | Only reachable under the ceiling AND with sufficient confirmed evidence |
| `razorpay_adapter.py` draft | Generated automatically | The function the pipeline calls has no way to request anything but `action="draft"` — submitting for real needs a separate, human-triggered call this pipeline never makes |
| `audit_log.py` | Yes, append-only | Every decision is recorded once; a duplicate `dispute_id` can't overwrite it (SQLite primary key), so nothing can be silently re-decided |
| `ml_scorer.py` | Not in the trusted path | Built and evaluated for comparison only; `policy.py` never imports it |
| `calibration.py` | Advisory only | Corrects the probability shown to a human; `policy.py`'s ceiling/threshold checks still run on the raw, uncalibrated score they were fuzz-tested against |

## Results

Measured on a held-out synthetic test set (900 disputes, generated with a
fixed seed, never touched during scorer or policy design):

| Metric | Value |
|---|---|
| Rule-based scorer AUC | 0.688 (dev) / 0.6882 (test) |
| Precision / Recall / F1 on `AUTO-CONTEST` calls | 0.703 / 0.569 / 0.629 |
| Action breakdown | 411 `AUTO-CONTEST`, 317 `HUMAN REVIEW`, 172 `ACCEPT LOSS` |
| False-positive cost, real pipeline | Rs 18,300.00 (122 false positives) |
| False-positive cost, naive "contest everything" baseline | Rs 58,800.00 (392 false positives) |
| Optional trained ML scorer AUC | 0.6882 — ties the rule-based scorer exactly (investigated why in `MISTAKES.md`) |
| Calibration error, raw scorer -> after isotonic calibration | 0.1218 -> 0.0849 (mean absolute error, dev-fit, measured on the held-out test set) |

All numbers above describe performance **inside this synthetic evaluation
environment only** — they are not a claim about real-world chargeback
outcomes.

## Honest limitations

- **The raw scorer's probabilities are still miscalibrated** — it ranks
  disputes reasonably (AUC 0.688) but is underconfident at the low end and
  overconfident at the high end. `calibration.py` corrects this with an
  isotonic curve fit on `dev.csv`, cutting the measured error on the
  held-out test set from 0.1218 to 0.0849 — but this correction is
  informational only. `policy.py`'s ceiling and threshold checks
  deliberately still run on the raw score, not the calibrated one, so the
  already fuzz-tested safety behavior doesn't need to be re-validated
  under new probability semantics.
- **The monetary ceiling isn't binding on this particular test set** — no
  dispute happens to fall where raising or lowering it would change the
  outcome. Its safety guarantee is proven separately by a fuzz test, not
  by this dataset.
- **The Razorpay adapter is mock-only.** There are no real Razorpay
  credentials here, and no code path that calls Razorpay's live servers.
  Field shapes were checked against Razorpay's public API docs for
  realism, but this has never been tested against the real API.
- **The evidence-category mapping in `razorpay_adapter.py` is my own
  judgment call**, not something Razorpay documents — their evidence
  categories are generic across dispute types, not specific to this
  project's 4 reason codes.
- **The SQLite audit trail is a single local file**, fine for a
  demo/single-instance deployment, not designed for multiple server
  instances writing concurrently across machines.
- **Public deployment status is unresolved.** `app_deployed.py` is built
  to run standalone with no separate API server, but as of this writing
  there's no confirmed, actually-public hosted URL for it — run it
  locally with the command below.

## Repository layout

- `generate_data.py`, `hidden_truth.py`, `config.py`, `models.py` — synthetic data generation
- `scorer.py`, `ml_scorer.py` — win-probability scoring (rule-based, primary; ML, comparison-only)
- `calibration.py` — isotonic calibration of the raw score against dev.csv, display-only
- `evidence.py` — PASS/WARN/FAIL evidence packet assembly
- `policy.py` — routing decision, monetary ceiling, expected value
- `audit_log.py` — SQLite decision log + idempotency
- `razorpay_adapter.py` — mock Razorpay dispute fetch + draft evidence submission
- `metrics.py`, `baseline.py`, `sensitivity.py` — evaluation on the held-out test set
- `api.py` — FastAPI backend
- `app.py`, `app_deployed.py`, `local_pipeline.py` — Streamlit frontends (API-backed and self-contained)
- `test_*.py` — the test suite (100 tests)
- `DATA_DICTIONARY.md` — every CSV column, explained
- `MISTAKES.md` — every real bug hit while building this, and how it was fixed
- `ARCHITECTURE.md` — the full diagram, color-coded against the trust boundary

## How to reproduce

```bash
pip install -r requirements.txt

# regenerate the synthetic dataset (train/dev/test.csv already included, but
# this reproduces them from scratch with the same seed)
python generate_data.py --n 6000 --seed 42

# check the generator doesn't leak the label into any single evidence field
python verify_no_leakage.py

# fit the calibration curve on dev.csv (also happens automatically, lazily,
# on first API/UI request if calibration_points.json doesn't exist yet)
python calibration.py

# run the full test suite
pytest -v

# run the API
uvicorn api:app --reload
curl -X POST http://127.0.0.1:8000/score -H "Content-Type: application/json" -d '{
  "dispute_id": "D_DEMO_1", "payment_id": "pay_demo", "reason_code": "item_not_received",
  "amount": 2000, "has_tracking_number": true, "has_delivery_confirmation": true,
  "has_signature_confirmation": true
}'

# run the Streamlit frontend (needs the API running above)
streamlit run app.py

# or run the self-contained version (no separate API needed)
streamlit run app_deployed.py
```
