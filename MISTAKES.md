# Mistakes I Made and What I Learned

This log records every real mistake, bug, or design gap found while
building this project — not manufactured examples. Each entry follows
the same structure (**Problem → Root Cause → Fix → Verified**) so it can
be read on its own, without needing the rest of the build history.
Every fix references the specific project principle it upholds (see
`README.md` for the full numbered principle list) and every verification
claim is backed by a real, runnable test or a real command's output —
not an assertion taken on faith.

**Summary table** (for a fast skim):

| # | Checkpoint | Issue | Principle at stake | Status |
|---|---|---|---|---|
| 1 | 1 | `None` treated as falsy could silently corrupt missingness handling | Missingness must not be conflated with "confirmed absent" | Fixed |
| 2 | 1 | Naive "reason-code-aware" model construction didn't actually work | Reason-code-aware design (#7) | Fixed, +0.104 AUC gap proven |
| 3 | 2 | — | Rule-based scorer AUC measured honestly on dev | Verified, 0.688 |
| 4 | 3 | Monetary ceiling could be silently bypassed by a confidence shortcut | Ceiling can never be overridden by model confidence (#6) | Fixed, 2000-case fuzz test |
| 5 | 4 | High P(win) possible with almost no confirmed evidence | Evidence completeness, not just probability (#7, #10) | Fixed with an evidence-gate |
| 6 | 5 | — | Honest metrics incl. calibration (#9) on real held-out test set | Verified, calibration gap disclosed |
| 7 | 6 | — | Naive baseline comparison, uncomfortable result kept honest | Verified |
| 8 | 7 | — | Threshold/ceiling sensitivity measured, not assumed | Verified |
| 9 | 8 | ML scorer tied rules exactly — investigated why, not just reported | Rules-first unless ML measurably wins (#2) | Verified, root cause explained |
| 10 | 9 | pydantic v1/v2 incompatibility crashed the API on a second machine | Cross-environment reliability | Fixed |
| 11 | 10 | Streamlit install silently broke FastAPI's pinned dependency | Regression safety across the whole test suite | Fixed, full suite re-verified |
| 12 | 11 | No persistent record; same dispute could be silently re-scored twice | Idempotency / audit trail for autonomous decisions | Fixed, 20-thread concurrency test |
| 13 | 12 | Testing the deployed app triggered noisy, unrelated Streamlit errors | Clean separation of UI from business logic | Fixed via refactor |
| 14 | 12 | Public demo's cached idempotency looked like a bug to a new user | UX around a safety feature must not look broken | Fixed |

---

## Checkpoint 1 — Synthetic Data Generator

### Mistake 1: Assumed `None` was truthy in Python

**Problem.** While designing missingness handling, assumed `if value:`
would treat `None` as truthy.

**Root cause.** Tested it directly — `None` is falsy in Python, same as
`False`. A naive `if dispute.has_tracking_number: score += 1` in the
scorer would therefore silently treat "unknown" identically to
"confirmed absent" — reintroducing the exact missingness bug already
fixed in the generator, one layer downstream in the scorer.

**Fix.** Scorer code branches explicitly on `is True` / `is False` /
`is None`, never on truthiness.

**Verified.** `test_scorer.py::test_unknown_evidence_is_neutral` asserts
unknown evidence produces exactly `0.5` (neutral), not the same
treatment as `False`.

---

### Mistake 2: First reason-code-aware model construction didn't work

**Problem.** Tried to build a "reason-code-aware" model by adding
`reason_code` as an extra one-hot column to a single LogisticRegression
alongside all 11 evidence fields.

**Root cause.** Measured the AUC gap vs. a reason-code-blind model:
essentially zero (`-0.001`). A plain logistic regression with an extra
column can only learn a fixed per-reason-code offset — it cannot learn
"only weight `has_tracking_number` when `reason_code =
item_not_received`, ignore it otherwise." That requires either explicit
interaction terms or genuinely separate models per reason code.

**Fix.** Trained one submodel per reason code, each using only that
reason's relevant evidence fields.

**Verified.** Real, reproducible gap: **+0.104 AUC** (0.586 -> 0.691).
This result directly justifies why Checkpoint 2's scorer applies
reason-code-specific rules instead of one global rule (project
principle: evidence must be reason-code aware).

---

## Checkpoint 2 — Rule-Based Scorer

**Finding (not a mistake, a verified result).** Built the reason-code-
aware rule-based scorer with equal-weight voting per relevant field,
squashed through a logistic function into a probability.

**Measured, on real `dev.csv`:** AUC **0.688** — very close to the
per-reason logistic regression submodel from Checkpoint 1 (0.691).

**Why this matters.** Most of the achievable signal comes from knowing
*which* fields matter per reason code, not from model sophistication on
top of that — directly relevant to Checkpoint 8's honest rules-vs-ML
comparison later.

---

## Checkpoint 3 — Policy Engine

### Mistake: Monetary ceiling could be silently bypassed

**Problem.** Built two intentionally-broken toy policy functions to
probe this risk: (1) a "skip ahead if very confident" shortcut let a
Rs 8,00,000 dispute at 98% confidence get auto-contested past a
Rs 50,000 ceiling; (2) a sneakier version where the ceiling check itself
silently included `and probability < 0.99`, which looked like a safety
rule but let a 99.5%-confidence case slip through the same way.

**Root cause.** Ceiling logic that reads `win_probability` anywhere in
its condition can always be defeated by a confident-enough (or
confidently *wrong*) model output.

**Fix.** Made the ceiling check the unconditional first line of
`decide()`, structurally unable to reference `win_probability` at all.

**Verified.** Fuzz test across 2000 random amount/probability
combinations above the ceiling — zero produced `AUTO-CONTEST`
(`test_policy.py::test_ceiling_holds_across_random_fuzzing`). This
directly satisfies the project principle that model confidence can
never override the monetary safety ceiling.

---

## Checkpoint 4 — Evidence Packet Assembler

### Mistake: High P(win) possible with almost no confirmed evidence

**Problem.** Tested whether a packet with only 1 `PASS` out of 3
relevant fields (2 `WARN`/unknown) would still be eligible for
`AUTO-CONTEST` under the existing Checkpoint 3 policy.

**Root cause.** It was eligible: `P(win)=0.697` cleared the 0.65
threshold, because unknown fields are neutral (0) rather than negative
in the scorer, so one strong `PASS` alone was enough to clear the bar.
The policy could auto-contest a dispute backed by only one confirmed
fact.

**Fix.** Added an evidence-completeness gate to `policy.decide()`: even
if `P(win)` clears the threshold, `AUTO-CONTEST` also requires a
majority (>50%) of relevant fields to be confirmed `PASS`, or it
downgrades to `HUMAN REVIEW`.

**Verified.** Confirmed the gate doesn't weaken the monetary ceiling
(still checked first, unconditionally) and doesn't block genuinely
strong cases (3/3 `PASS` still auto-contests) --
`test_policy.py::test_high_probability_but_mostly_unconfirmed_evidence_blocks_auto_contest`,
`test_policy.py::test_majority_confirmed_evidence_allows_auto_contest`,
`test_policy.py::test_evidence_gate_never_overrides_the_ceiling`.

---

## Checkpoint 5 — Metrics

**Finding.** Ran the full scorer -> evidence -> policy pipeline against
the held-out test set (900 disputes, touched here for the first time in
the project) with `AUTO-CONTEST` treated as a positive prediction:

- Precision: 0.703, Recall: 0.569, F1: 0.629
- False-positive cost: Rs 5,21,716.65 across 122 false positives
  (contest_cost + lost amount, for every `AUTO-CONTEST` that lost)
- Action breakdown: 411 `AUTO-CONTEST`, 317 `HUMAN REVIEW`,
  172 `ACCEPT LOSS`

**Honest disclosure, not hidden.** The calibration check (5 bins) showed
the scorer is **not** well-calibrated: underconfident at the low end
(predicted ~0.125, actual ~0.349) and overconfident at the high end
(predicted ~0.884, actual ~0.771). This is expected -- the logistic
squashing function in `scorer.py` was hand-picked (`k=2.5`) to look
reasonable, not fit to match true probabilities. The scorer ranks
disputes reasonably (AUC 0.688) but its raw probability numbers should
not be read as precise likelihoods. Stated plainly here and in the
README rather than hidden.

---

## Checkpoint 6 — Naive Baseline Comparison

**Finding -- an honest, uncomfortable result, kept rather than hidden.**
Built the "contest everything" naive baseline and compared it against
the real pipeline on the same held-out `test.csv`:

| Metric | Naive (contest all) | Real pipeline |
|---|---|---|
| Precision | 0.564 | 0.703 |
| Recall | 1.000 | 0.569 |
| F1 | 0.722 | 0.629 |
| False-positive cost | Rs 17,29,985.26 (392 FPs) | Rs 5,21,716.65 (122 FPs) |
| Net money recovered | Rs 19,83,612.30 | Rs 11,62,088.53 |

The naive baseline's F1 and total net-recovered money are actually
*higher* than the real pipeline's. Verified this makes sense before
treating it as a problem: F1 and total-recovered both reward raw
volume, and the naive baseline contests all 900 disputes while the real
pipeline only auto-contests 411 -- more attempts means more total wins
even with a worse hit rate. **False-positive cost is the number that
matters most for an autonomous system**, and there the real pipeline
wins by more than 3x (Rs 5.2L vs Rs 17.3L) with a third of the bad calls
(122 vs 392). This tradeoff -- lower recall in exchange for lower risk
per autonomous decision -- is the deliberate design goal of the monetary
ceiling and evidence-completeness gate (Checkpoints 3-4), not a flaw,
and is stated as such in the pitch rather than hidden behind the F1
number alone.

---

## Checkpoint 7 — Sensitivity Analysis

**Findings.** Swept `AUTO_CONTEST_THRESHOLD` from 0.50-0.90 and
`MONETARY_CEILING` from Rs 5,000-5,00,000 on the real test set:

- Threshold sweep confirmed the expected precision/recall tradeoff
  cleanly and monotonically (e.g. 0.65 -> precision 0.703/recall 0.569;
  0.90 -> precision 0.792/recall 0.270). Also found 0.55, 0.60, and 0.65
  all produce *identical* results -- no test dispute has a `P(win)` in
  that narrow band, so the current threshold has unused slack.
- Ceiling sweep found raising the ceiling from Rs 10,000 to Rs 5,00,000
  changes **nothing** in this test set -- identical precision, identical
  counts. The Rs 50,000 ceiling isn't actually binding on this
  particular synthetic dataset (no disputes fall where it would matter
  day to day). Stated honestly rather than implying the ceiling is
  doing visible work here -- its value is proven separately by the
  Checkpoint 3 fuzz test (it *would* block an over-ceiling auto-contest
  if one existed), not by this sensitivity sweep.

---

## Checkpoint 8 — Optional ML Upgrade

**Finding -- a tie, investigated rather than just reported.** Trained a
per-reason-code Logistic Regression (same submodel structure validated
in Checkpoint 1) on `train.csv`, evaluated honestly on `test.csv`
(never touched during training or rule design) against the rule-based
`scorer.py` on the same test set:

- Rule-based AUC: **0.6882**
- ML scorer AUC: **0.6882** (identical to 4 decimal places)

Rather than treat this as a disappointing null result, inspected the ML
model's actual learned coefficients directly. For `item_not_received`:
`has_tracking_number=0.748`, `has_delivery_confirmation=0.903`,
`has_signature_confirmation=0.834` -- nearly equal, with no strong
preference for any one field. Traced this back to `hidden_truth.py`:
`RELEVANT_FIELD_RATE_IF_LEGIT`/`NOT_LEGIT` apply the *same* correlation
strength to every relevant field for a reason code, by design. There is
no hidden per-field weighting pattern in the data for ML to discover,
so an algorithm free to learn any weights converges to nearly the same
equal weighting hand-picked in `scorer.py`'s `FIELD_WEIGHT = 1.0`.

**Decision.** Per the project principle that a rule-based scorer stays
primary unless ML measurably beats it, kept the rule-based scorer as
primary. Documented as a genuine, explained finding -- not an
unexplained tie.

---

## Checkpoint 9 — FastAPI Backend

### Finding: verified end-to-end, not just unit-tested

Built `api.py` with a single `/score` endpoint that calls `scorer.py`,
`evidence.py`, and `policy.py` directly -- zero business logic
duplicated in the API layer. Verified by actually running the server
and sending real HTTP requests, not just unit tests: the exact
Checkpoint 3 dangerous case (Rs 8,00,000 dispute with strong evidence)
correctly returned `HUMAN REVIEW` with the ceiling-exceeded reason
message through the full HTTP round trip -- proving the API wrapper
didn't accidentally reimplement (and potentially weaken) the safety
logic. Also added a cross-check test comparing the API's evidence
output directly against calling `evidence.assemble()` in-process, to
catch any future drift between the two.

Small technical note: FastAPI's `TestClient` needs the `httpx` package
installed separately -- not automatically pulled in by `fastapi` itself.

### Mistake: pydantic v1/v2 incompatibility on a different machine

**Problem.** Testing `api.py` on a second machine (Windows, separate
pytest run) failed with `AttributeError: 'DisputeRequest' object has no
attribute 'model_dump'`.

**Root cause.** `model_dump()` only exists in pydantic v2; that machine
had an older pydantic v1 already installed (visible from the stack
trace using the older `requests`-based `TestClient` instead of
`httpx`).

**Fix.** One-line compatibility check:
`request.model_dump() if hasattr(request, "model_dump") else
request.dict()` -- works on either version without forcing an upgrade
that could break other already-working dependencies on that machine.

**Verified.** Re-ran the full test suite on the second machine after
the fix -- all tests passed.

**Lesson.** Don't assume every environment has the same library
versions, especially for a library that made a breaking v1->v2 change to
a commonly-used method name.

---

## Checkpoint 10 — Streamlit Frontend

**Design decision.** Built `app.py` with two tabs: "Score a Dispute"
(calls the real API from Checkpoint 9, zero scoring logic in the
frontend itself) and "Model Performance Dashboard" (visualizes
precision/recall/calibration/sensitivity from Checkpoints 5-7, reusing
those exact tested modules directly rather than reimplementing any
calculation). Verified end-to-end with `curl` before trusting the UI:
sent the exact payload shape the Streamlit form builds (mixed
True/None/False evidence) to the real running API and confirmed the
response matched expected values (`P(win)=0.5` for one `PASS` + one
`WARN` + one `FAIL`, since they cancel out -> `HUMAN REVIEW`). Chose to
add the dashboard tab beyond the minimum single-dispute form because it
showcases the honest metrics work from earlier checkpoints (including
the not-fully-calibrated scorer and the naive-baseline comparison)
rather than hiding them -- consistent with the project principle that UI
should not be flashy at the expense of substance.

### Mistake: installing Streamlit silently broke FastAPI's pinned dependency

**Problem.** Installing `streamlit` pulled in a newer `starlette`
(1.6.0), but the machine's existing `fastapi` (0.68.2, quite old) was
hard-pinned to `starlette==0.14.2`.

**Root cause.** pip explicitly warned about this incompatibility during
install rather than failing silently -- a real, confirmed dependency
conflict, not a guess.

**Fix.** `pip install --upgrade fastapi` to bring FastAPI itself to a
version compatible with the newer starlette.

**Verified.** Re-ran the *full* test suite afterward (62/62 passing,
not just the tests for the thing just added) and confirmed the API
still started cleanly -- didn't just trust that the upgrade "probably
worked."

**Lesson.** When installing a new library changes a shared dependency's
version, always re-run the full test suite afterward -- a change in one
part of the stack can silently affect unrelated code sitting on the
same shared dependency.

---

## Checkpoint 11 — SQLite Audit Trail + Idempotency

### Gap found via competitive research, not internal testing

**Problem.** While researching competing Track 02 submissions for
calibration, found that another repo (built around payment-retry
recovery) tested idempotency and concurrent-request handling more
rigorously than this project did at the time -- a real, legitimate gap.
This project had no persistent record of past decisions, and could
silently re-score the same `dispute_id` multiple times (e.g. on a
network retry) -- a real risk for a system meant to make autonomous
financial decisions.

**Fix.** Built `audit_log.py`: a local SQLite file (`audit_log.db`)
storing every decision keyed by `dispute_id` as a `PRIMARY KEY`, so a
duplicate `dispute_id` physically cannot be double-inserted, even under
a race condition. Wired into `api.py`'s `/score` endpoint: submitting
the same `dispute_id` twice now returns `replayed=true` with the
byte-for-byte identical original decision.

**Verified.**
- A 20-thread concurrency fuzz test -- all 20 threads converged to the
  identical stored decision, not double-computed
  (`test_audit_log.py::test_concurrent_duplicate_submissions_only_compute_once`).
- End-to-end through a real HTTP round trip: identical `win_probability`
  matched to 16 decimal places on replay.

**Real gotcha along the way.** Had to add explicit test isolation
(deleting `audit_log.db` before/after each test run) once tests started
writing to a persistent file -- otherwise re-running the suite twice in
a row would make previously-tested `dispute_id`s always show as
replayed from the prior run, which could mask a real bug in future test
runs.

---

## Checkpoint 12 — Public Deployment

### Mistake: mixing UI code with testable logic broke test isolation

**Problem.** The first version of `app_deployed.py` (the self-contained
public-deployment build, calling the pipeline directly instead of over
HTTP) mixed the scoring logic directly into the same file as the
Streamlit UI code.

**Root cause.** Importing that file for tests triggered Streamlit to
try to render the entire page outside a real browser context, producing
dozens of harmless-but-noisy "missing ScriptRunContext" warnings and
making actual test output hard to read.

**Fix.** Extracted the pipeline-calling logic into a separate module,
`local_pipeline.py`, with zero Streamlit imports; `app_deployed.py` now
just imports and calls it.

**Verified.** This also enabled a genuinely valuable cross-check test:
`score_dispute_locally()` and the real `api.py`'s `/score` endpoint are
asserted to produce byte-identical output for the same input
(`test_local_pipeline.py::test_matches_api_pipeline_exactly`), proving
the deployed version's logic hasn't silently diverged from the tested
API. Kept the original `app.py` (calls the real API over HTTP) for
local development and pitch-video demos of the actual backend + audit
trail; `app_deployed.py` exists specifically so a reviewer can click
one public link with zero setup on their end.

### Mistake: a safety feature's UX looked like a bug on first use

**Problem.** Testing the live public `app_deployed.py` demo: left the
"Dispute ID" field at its default value while changing evidence radios
and re-clicking "Score Dispute." Got back the *original* decision from
an earlier test via the idempotency guarantee (Checkpoint 11), not a
fresh computation of the new evidence.

**Root cause.** This was not a bug -- idempotency was working exactly as
designed. But it was correctly signaled only by a small banner
("already scored before"), which a first-time demo user could easily
miss or misread as broken behavior, since they hadn't consciously
reused the same ID on purpose.

**Fix.** Added auto-generated random dispute IDs (`D_DEMO_<8 hex
chars>`) as the default value in both `app.py` and `app_deployed.py`,
persisted via `st.session_state` so it stays stable across reruns, plus
a "New ID" button to explicitly get a fresh one. Each test now scores
genuinely fresh by default; a user who *wants* to demonstrate the
idempotency guarantee can still manually reuse the same ID on purpose.

**Verified.** Full test suite (72/72) still passes, since this only
touched Streamlit widget code, not the tested pipeline.

**Why this belongs in the log.** A safety feature that confuses the
person using it is a real design failure mode, even when the underlying
logic is completely correct -- worth treating as seriously as a code
bug, not dismissed as "user error."