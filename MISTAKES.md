# Mistakes and Fixes

This is a log of every real mistake or bug I ran into while building this
project — not manufactured examples. Each entry follows the same structure
(**Problem → Root Cause → Fix → Verified**) so it can be read on its own.
Every verification claim below is backed by a real, runnable test or a real
command's output, not just an assertion that it works.

**Summary:**

| # | Mistake | Why it mattered | Status |
|---|---|---|---|
| 1 | Assumed `None` was truthy in Python | Would have silently treated "unknown" evidence the same as "confirmed absent" | Fixed |
| 2 | First attempt at a reason-code-aware model didn't actually use the reason code | A single model with an extra column can't learn different weightings per reason | Fixed, +0.104 AUC after redesign |
| 3 | Monetary ceiling could be bypassed by a confidence shortcut | A confident (or wrong) model could push a large dispute past the safety limit | Fixed, verified with a 2000-case fuzz test |
| 4 | High win-probability possible with almost no confirmed evidence | Could auto-contest on one confirmed fact and two unknowns | Fixed with an evidence-completeness gate |
| 5 | pydantic v1/v2 incompatibility crashed the API on a second machine | Worked on my machine, broke on a fresh install | Fixed with a one-line compatibility check |
| 6 | Installing Streamlit silently broke FastAPI's pinned dependency | A new library install broke an unrelated, already-working part of the stack | Fixed, full test suite re-verified |
| 7 | No persistent record — the same dispute could be silently re-scored twice | A network retry could double-process an autonomous financial decision | Fixed with a SQLite audit trail + 20-thread concurrency test |
| 8 | Mixing UI code with testable logic broke test isolation | Importing the app for tests triggered noisy Streamlit rendering errors | Fixed via refactor into a separate module |
| 9 | A safety feature's UX looked like a bug on first use | Idempotent replay was working correctly but easy to misread as broken | Fixed with auto-generated fresh IDs |
| 10 | Invalid `reason_code` crashed the API with a 500 instead of a 422 | Unvalidated input reached a dictionary lookup with no fallback | Fixed with input validation at the API boundary |
| 11 | A cost metric contradicted the policy engine's own assumption | The reported false-positive cost was double-counting a loss | Fixed, real numbers recalculated |

---

## 1. Assumed `None` was truthy in Python

**Problem.** While designing how missing evidence should be handled, I
assumed `if value:` would treat `None` as truthy.

**Root cause.** Tested it directly — `None` is falsy in Python, exactly
like `False`. A naive `if dispute.has_tracking_number: score += 1` in the
scorer would have silently treated "unknown" identically to "confirmed
absent," reintroducing the exact bug I'd already fixed in the data
generator, one layer downstream in the scorer.

**Fix.** The scorer branches explicitly on `is True` / `is False` /
`is None`, never on truthiness.

**Verified.** `test_scorer.py::test_unknown_evidence_is_neutral` asserts
unknown evidence produces exactly `0.5` (neutral), not the same treatment
as `False`.

---

## 2. First attempt at a reason-code-aware model didn't actually use the reason code

**Problem.** I tried to make a model "reason-code-aware" by adding
`reason_code` as an extra one-hot column to a single logistic regression
alongside all 11 evidence fields.

**Root cause.** I measured the AUC gap against a reason-code-blind model
and got essentially zero (`-0.001`). A plain logistic regression with one
extra column can only learn a fixed per-reason-code offset — it can't
learn "only weight `has_tracking_number` when the reason is
`item_not_received`, ignore it otherwise." That needs either explicit
interaction terms or genuinely separate models per reason code.

**Fix.** Trained one submodel per reason code, each using only that
reason's relevant evidence fields.

**Verified.** Real, reproducible gap: **+0.104 AUC** (0.586 → 0.691) once
switched to per-reason submodels — this is why the rule-based scorer also
applies reason-code-specific logic instead of one global rule.

---

## 3. Monetary ceiling could be silently bypassed

**Problem.** I deliberately built two broken toy policy functions to
probe this risk: one let a very confident model skip past the ceiling for
a large dispute; a sneakier version hid `and probability < 0.99` inside
the ceiling check itself, which looked like a safety rule but let a
99.5%-confidence case slip through the same way.

**Root cause.** Any ceiling check that reads `win_probability` anywhere in
its condition can always be defeated by a confident-enough (or confidently
*wrong*) model output.

**Fix.** Made the ceiling check the unconditional first line of
`decide()`, structurally unable to reference `win_probability` at all.

**Verified.** A fuzz test across 2000 random amount/probability
combinations above the ceiling — zero produced `AUTO-CONTEST`
(`test_policy.py::test_ceiling_holds_across_random_fuzzing`).

---

## 4. High win-probability possible with almost no confirmed evidence

**Problem.** I tested whether a packet with only 1 `PASS` out of 3
relevant fields (the other 2 unknown) would still be eligible for
`AUTO-CONTEST`.

**Root cause.** It was eligible: `P(win)=0.697` cleared the 0.65 threshold,
because unknown fields are neutral (0) rather than negative in the scorer,
so one strong `PASS` alone was enough to clear the bar. The policy could
auto-contest a dispute backed by only one confirmed fact.

**Fix.** Added an evidence-completeness gate to `policy.decide()`: even if
`P(win)` clears the threshold, `AUTO-CONTEST` also requires a majority
(>50%) of relevant fields to be confirmed `PASS`, or it downgrades to
`HUMAN REVIEW`.

**Verified.** Confirmed the gate doesn't weaken the monetary ceiling
(still checked first, unconditionally) and doesn't block genuinely strong
cases (3/3 `PASS` still auto-contests) — see
`test_policy.py::test_high_probability_but_mostly_unconfirmed_evidence_blocks_auto_contest`
and the two related tests around it.

---

## 5. pydantic v1/v2 incompatibility crashed the API on a second machine

**Problem.** Testing the API on a second machine (Windows, separate pytest
run) failed with `AttributeError: 'DisputeRequest' object has no attribute
'model_dump'`.

**Root cause.** `model_dump()` only exists in pydantic v2; that machine
already had an older pydantic v1 installed (visible from the stack trace
using the older `requests`-based `TestClient` instead of `httpx`).

**Fix.** A one-line compatibility check:
`request.model_dump() if hasattr(request, "model_dump") else request.dict()`
— works on either version without forcing an upgrade that could break
other already-working dependencies on that machine.

**Verified.** Re-ran the full test suite on the second machine after the
fix — all tests passed.

**Lesson.** Don't assume every environment has the same library versions,
especially for a library that made a breaking v1→v2 change to a
commonly-used method name.

---

## 6. Installing Streamlit silently broke FastAPI's pinned dependency

**Problem.** Installing `streamlit` pulled in a newer `starlette` (1.6.0),
but the machine's existing `fastapi` (0.68.2, quite old) was hard-pinned
to `starlette==0.14.2`.

**Root cause.** pip explicitly warned about this incompatibility during
install — a real, confirmed dependency conflict, not a guess.

**Fix.** `pip install --upgrade fastapi` to bring FastAPI to a version
compatible with the newer starlette.

**Verified.** Re-ran the *full* test suite afterward (not just the tests
for the thing I'd just added) and confirmed the API still started cleanly.

**Lesson.** When installing a new library changes a shared dependency's
version, always re-run the full test suite afterward — a change in one
part of the stack can silently affect unrelated code sitting on the same
shared dependency.

---

## 7. No persistent record — the same dispute could be silently re-scored twice

**Problem.** While comparing notes against a similar project, I realized
this system had no persistent record of past decisions and could silently
re-score the same `dispute_id` multiple times (e.g. on a network retry) —
a real risk for a system meant to make autonomous financial decisions.

**Fix.** Built a local SQLite audit log (`audit_log.db`) storing every
decision keyed by `dispute_id` as a `PRIMARY KEY`, so a duplicate
`dispute_id` physically cannot be double-inserted, even under a race
condition. Wired into the `/score` endpoint: submitting the same
`dispute_id` twice now returns `replayed=true` with the byte-for-byte
identical original decision.

**Verified.**
- A 20-thread concurrency fuzz test — all 20 threads converged to the
  identical stored decision, not double-computed
  (`test_audit_log.py::test_concurrent_duplicate_submissions_only_compute_once`).
- End-to-end through a real HTTP round trip: identical `win_probability`
  matched to 16 decimal places on replay.

**Real gotcha along the way.** Had to add explicit test isolation
(deleting the database file before/after each test run) once tests
started writing to a persistent file — otherwise re-running the suite
twice in a row would make previously-tested `dispute_id`s always show as
replayed from the prior run, which could mask a real bug in future test
runs.

---

## 8. Mixing UI code with testable logic broke test isolation

**Problem.** The first version of the self-contained deployment build
mixed the scoring logic directly into the same file as the Streamlit UI
code.

**Root cause.** Importing that file for tests triggered Streamlit trying
to render the entire page outside a real browser context, producing
dozens of harmless-but-noisy "missing ScriptRunContext" warnings and
making actual test output hard to read.

**Fix.** Extracted the pipeline-calling logic into a separate module with
zero Streamlit imports; the deployed app now just imports and calls it.

**Verified.** This also enabled a genuinely valuable cross-check test: the
extracted function and the real API's `/score` endpoint are asserted to
produce byte-identical output for the same input, proving the deployed
version's logic hasn't silently diverged from the tested API.

---

## 9. A safety feature's UX looked like a bug on first use

**Problem.** Testing the live public demo: I left the "Dispute ID" field
at its default value while changing evidence and re-clicking "Score
Dispute." I got back the *original* decision from an earlier test via the
idempotency guarantee, not a fresh computation of the new evidence.

**Root cause.** This wasn't a bug — idempotency was working exactly as
designed. But it was signaled only by a small banner ("already scored
before"), which a first-time user could easily miss or misread as broken
behavior, since they hadn't consciously reused the same ID on purpose.

**Fix.** Auto-generate a fresh random dispute ID by default
(`D_DEMO_<8 hex chars>`), persisted for the session so it stays stable
across reruns. Each test now scores genuinely fresh by default; a user
who wants to demonstrate the idempotency guarantee can still manually
reuse the same ID on purpose.

**Verified.** Full test suite still passed, since this only touched
Streamlit widget code, not the tested pipeline.

**Why this belongs in the log.** A safety feature that confuses the
person using it is a real design failure mode, even when the underlying
logic is completely correct — worth treating as seriously as a code bug,
not dismissed as "user error."

---

## 10. Invalid `reason_code` crashed the API with a 500 instead of a 422

**Problem.** The API accepted any string for `reason_code` with no
validation. I confirmed directly that
`predict_win_probability({"reason_code": "not_a_real_reason"})` raises an
unhandled `KeyError` inside the scorer (it indexes a lookup dict with no
fallback) — FastAPI would surface that as a 500, not a clean validation
error.

**Root cause.** Nothing at the API boundary checked `reason_code` against
the 4 known values before handing it to the scoring pipeline.

**Fix.** The endpoint now checks the incoming `reason_code` against the
known list first and returns a proper 422 before the dispute is ever
built or passed to the scorer.

**Verified.** Added a test that sends a bogus `reason_code` and asserts a
422 comes back, instead of the request reaching the pipeline at all.

---

## 11. A cost metric contradicted the policy engine's own assumption

**Problem.** The "false-positive cost" calculation — used in the main
metrics module, the naive-baseline comparison, and the sensitivity sweep
— charged the *disputed amount plus a flat fee* for every lost
auto-contest. But the policy engine's own expected-value formula assumes
losing a contest costs nothing beyond the fee, since the disputed amount
is already gone (reversed by the chargeback) whether or not you contest
it.

**Root cause.** In a real chargeback, the money leaves the merchant when
the dispute is filed, not when a contest is lost — contesting is only
ever an attempt to recover money already gone. Charging the amount again
on a loss double-counted a cost that was already implied by "not
recovering the money."

**Fix.** Changed all three places to charge just the flat contest fee per
lost auto-contest, matching the policy engine's own model, and
recalculated the headline numbers that had been reported with the old,
incorrect formula: false-positive cost on the real held-out test set
dropped from a previously-reported Rs 5,21,716.65 to a corrected
**Rs 18,300.00** for the real pipeline (122 false positives), and from
Rs 17,29,985.26 to **Rs 58,800.00** for the naive "contest everything"
baseline (392 false positives). The comparative conclusion didn't change —
the real pipeline still wins by the same ~3x margin, since with a flat
fee the cost ratio is mechanically identical to the false-positive-count
ratio.

**Verified.** Recomputed the real numbers from the held-out test set with
both the old and new formulas to confirm the old numbers matched what had
previously been reported, and updated a hardcoded test expectation that
had baked in the old formula.
