# Design Notes

Why this project is built the way it is. For the bug-by-bug history —
what broke, why, and how it was fixed — see `MISTAKES.md` instead; this
file is about the decisions, not the debugging.

## Why a rule-based scorer first, ML second and optional

An interpretable rule-based scorer is easy to defend in front of a
reviewer: every score can be explained as "3 of 3 relevant fields
confirmed" rather than "the model said so." A trained model (Logistic
Regression, one submodel per reason code) was built and evaluated
honestly against the same held-out test set — it tied the rule-based
scorer's AUC exactly (0.6882 both), which was investigated rather than
just reported: the synthetic generator gives every relevant field equal
correlation strength by design, so there's no hidden per-field weighting
pattern for a model to discover that the hand-picked equal weighting in
`scorer.py` doesn't already capture. The rule-based scorer stays primary;
`policy.py` never imports `ml_scorer.py`.

## Why 4 reason codes with their own relevant evidence fields

Real chargebacks come with a reason code (item not received, item not as
described, unauthorized transaction, duplicate charge), and the evidence
that actually matters is different for each one — a tracking number is
irrelevant to a duplicate-charge dispute. `scorer.py` and `evidence.py`
both read evidence only through
`config.RELEVANT_EVIDENCE_BY_REASON[reason_code]`, so evidence from the
wrong category structurally cannot influence a score, rather than relying
on remembering to filter it out somewhere.

## Why `None` is a third value, not a stand-in for `False`

Every evidence field is `bool | None`: confirmed present, confirmed
absent, or not collected. Collapsing "unknown" into "confirmed absent"
would make a system that's never actually checked something behave as
if it had proof against the dispute, which is a worse failure mode than
just being uncertain. The scorer treats `None` as neutral (contributes
nothing to the score either direction), not negative.

## Why a monetary ceiling that can't read the model's probability

The single most important safety property in this project: no matter
how confident the scorer is, a dispute above `MONETARY_CEILING` is always
routed to `HUMAN REVIEW`. This is enforced by making the ceiling check
the unconditional first line of `policy.decide()`, before
`win_probability` is read at all — not by adding a condition that checks
the probability is low enough, which could always be defeated by a
confident (or confidently wrong) score. Proven with a 2000-case fuzz
test across random amount/probability combinations, not just a couple
of hand-picked examples.

## Why an evidence-completeness gate on top of the probability threshold

A dispute can clear the probability threshold for `AUTO-CONTEST` with
only one confirmed fact and two unknowns, because unknowns are neutral
rather than negative. That's not a safe bar for an autonomous financial
decision, so `AUTO-CONTEST` also requires a majority of the relevant
evidence fields to be confirmed `PASS`, independent of how high the
probability is.

## Why SQLite for the audit trail, and why it enforces idempotency

A local SQLite file with `dispute_id` as the primary key means a
duplicate submission (e.g. a network retry) cannot be double-inserted,
even under a race — verified with a 20-thread concurrency test, not just
assumed. This was added after noticing that a comparable project handled
duplicate-request safety more rigorously than this one did at the time.
It's a single local file, which is enough for a demo or a single-instance
deployment; it isn't designed for multiple server instances writing to
it concurrently across machines.

## Why the Razorpay adapter is mock-only and draft-only

There are no Razorpay credentials available for this project, and
building an untested live-submission path would be both unverifiable and
in tension with a defense-only, honest-metrics project — an autonomous
system probably shouldn't submit real evidence to a real dispute without
a human confirming it anyway. `razorpay_adapter.py` mirrors the real
Disputes API's field shapes (checked against Razorpay's public docs,
including the `contest` endpoint's own `action: "draft" | "submit"`
field) closely enough that a real integration could plug in later without
touching `scorer.py`/`evidence.py`/`policy.py`. The function the pipeline
actually calls, `generate_contest_draft()`, has no parameter that could
ever ask for `"submit"` — that's a deliberate structural choice, mirroring
how the monetary ceiling is enforced.

The mapping from this project's evidence fields (`has_tracking_number`,
etc.) to Razorpay's evidence categories (`shipping_proof`,
`customer_communication`, etc.) is my own best-effort judgment call, not
something Razorpay documents — their categories are generic across all
dispute types, not specific to these 4 reason codes.

## Why the deployed Streamlit app is a separate file from the local one

`app.py` calls the FastAPI backend over real HTTP, which is the more
realistic integration test of the two but requires a server running
alongside it. `app_deployed.py` calls the same pipeline functions
directly through `local_pipeline.py` (zero Streamlit imports, so it can
be unit-tested), so it can run standalone with nothing else started —
useful for a reviewer who just wants to click one link. Both are checked
against each other: `test_local_pipeline.py::test_matches_api_pipeline_exactly`
asserts the two paths produce byte-identical output for the same input.

## Known limitations, in more detail than the README's summary

- The scorer's raw probabilities are not well-calibrated at the extremes
  (see `MISTAKES.md` and the dashboard's calibration check) — they rank
  disputes reasonably but shouldn't be read as precise likelihoods.
- The monetary ceiling and evidence gate are proven correct by targeted
  tests, not by this particular dataset happening to exercise them —
  raising or lowering the ceiling changes nothing on the current test
  set because no dispute in it happens to sit near that boundary.
- Every metric in this project is scoped to the synthetic evaluation
  environment. Nothing here is a claim about real-world chargeback win
  rates, and the README says so explicitly rather than implying it.
- This system has never been run against a real payment processor of any
  kind. The Razorpay field shapes are a best-effort match to public docs,
  not something verified against a live sandbox account.
