# Mistakes I Made and What I Learned

## Checkpoint 1

### 1. Assumed `None` was truthy in Python
While designing missingness handling, I guessed `if value:` would treat
`None` as truthy. Tested it directly — it's actually falsy, same as
`False`. This meant a naive `if dispute.has_tracking_number: score += 1`
in the future scorer would silently treat "unknown" identically to
"confirmed absent" — exactly the missingness bug we'd just fixed in the
generator, reappearing in the scorer instead. Fix: scorer code must
branch explicitly on `is True` / `is False` / `is None`, not rely on
truthiness.

### 2. First reason-code-aware model construction was flawed
Tried to build a "reason-code-aware" model by just adding `reason_code`
as an extra one-hot column to a single LogisticRegression alongside all
11 evidence fields. Measured AUC gap vs the reason-code-blind model:
essentially zero (-0.001). Root cause: a plain logistic regression with
an extra column can only learn a fixed per-reason-code offset — it can't
learn "only weight `has_tracking_number` when `reason_code =
item_not_received`, ignore it otherwise." That requires either explicit
interaction terms or genuinely separate models per reason code.

Fix: trained one submodel per reason code, each using only that reason's
relevant evidence fields. Real gap: **+0.104 AUC** (0.586 -> 0.691) —
meaningful and reproducible, and it directly justifies why Checkpoint 2's
scorer applies reason-code-specific rules instead of one global rule.


## Checkpoint 2

### Rule-based scorer AUC on real dev set
Built the reason-code-aware rule-based scorer with equal-weight voting
per relevant field, squashed through a logistic function to produce a
probability. Measured AUC on the actual dev.csv (not a toy example):
**0.688** -- very close to the per-reason logistic regression submodel
from Checkpoint 1 (0.691). This is a good sign: most of the achievable
signal comes from knowing WHICH fields matter per reason code, not from
sophisticated modeling on top of that. Directly relevant for Checkpoint
8's honest rules-vs-ML comparison later.


## Checkpoint 3

### Proved the monetary ceiling danger, then fixed it structurally
Built two intentionally-broken toy policy functions first: one where a
"skip ahead if very confident" shortcut let a Rs 8,00,000 dispute at 98%
confidence get auto-contested past a Rs 50,000 ceiling; a sneakier one
where the ceiling check itself silently included `and probability < 0.99`,
which looked like a safety rule but let a 99.5%-confidence case slip
through the same way. Fixed by making the ceiling check the unconditional
first line of `decide()`, structurally unable to reference
`win_probability` at all. Verified with a fuzz test across 2000 random
amount/probability combinations above the ceiling -- zero produced
AUTO-CONTEST.


## Checkpoint 4

### Found and fixed a real gap between "high P(win)" and "enough confirmed evidence"
While building the evidence packet assembler, tested whether a packet
with only 1 PASS out of 3 relevant fields (2 WARN/unknown) would still
be eligible for AUTO-CONTEST under the existing Checkpoint 3 policy.
It was: P(win)=0.697 cleared the 0.65 threshold, because unknown fields
are neutral (0) rather than negative in the scorer, so 1 strong PASS was
enough to clear the bar alone. This meant the policy could auto-contest
a dispute where we only actually CONFIRMED one piece of evidence.

Fixed by adding an evidence-completeness gate to policy.decide(): even
if P(win) clears the threshold, AUTO-CONTEST also now requires a
majority (>50%) of relevant fields to be confirmed PASS, or it downgrades
to HUMAN REVIEW. Verified this doesn't weaken the monetary ceiling (still
checked first, unconditionally) and doesn't block genuinely strong cases
(3/3 PASS still auto-contests).


## Checkpoint 6

### Naive baseline comparison -- an honest, slightly uncomfortable result
Built the "contest everything" naive baseline and compared it against
the real pipeline on the same held-out test.csv:

| Metric | Naive (contest all) | Real pipeline |
|---|---|---|
| Precision | 0.564 | 0.703 |
| Recall | 1.000 | 0.569 |
| F1 | 0.722 | 0.629 |
| False-positive cost | Rs 17,29,985.26 (392 FPs) | Rs 5,21,716.65 (122 FPs) |
| Net money recovered | Rs 19,83,612.30 | Rs 11,62,088.53 |

Honest finding: the naive baseline's F1 and total net-recovered money are
actually HIGHER than the real pipeline's. Verified this makes sense
before treating it as a "problem": F1 and total-recovered both reward
raw volume, and the naive baseline contests all 900 disputes while the
real pipeline only auto-contests 411 -- more attempts means more total
wins even with a worse hit rate. But false-positive cost is the number
that matters most for an AUTONOMOUS system, and there the real pipeline
wins by more than 3x (Rs 5.2L vs Rs 17.3L) with a third of the bad calls
(122 vs 392). The tradeoff (lower recall, in exchange for lower risk per
autonomous decision) is the deliberate design goal of the monetary
ceiling and evidence-completeness gate from Checkpoints 3-4, not a flaw.
This needs to be stated honestly in the pitch, not hidden behind the F1
number alone.


## Checkpoint 7

### Sensitivity analysis revealed two honest, useful findings
Swept AUTO_CONTEST_THRESHOLD from 0.50 to 0.90 and MONETARY_CEILING from
Rs 5,000 to Rs 5,00,000 on the real test set:

- Threshold sweep confirmed the expected precision/recall tradeoff
  cleanly and monotonically (e.g. 0.65 -> precision 0.703/recall 0.569;
  0.90 -> precision 0.792/recall 0.270). Also found that 0.55, 0.60, and
  0.65 all produce IDENTICAL results -- no test dispute has a P(win) in
  that narrow band, so our current threshold has some unused "slack".

- Ceiling sweep found something more surprising: raising the ceiling
  from Rs 10,000 all the way to Rs 5,00,000 changes NOTHING in this test
  set -- identical precision, identical counts. This means our current
  Rs 50,000 ceiling isn't actually binding on this particular synthetic
  dataset (no disputes fall in the range where it would matter day to
  day). Worth stating honestly rather than implying the ceiling is doing
  visible work here -- its value is proven separately by the Checkpoint 3
  fuzz test (it WOULD block an over-ceiling auto-contest if one existed),
  not by this sensitivity sweep.


## Checkpoint 8

### Trained ML scorer tied the rule-based scorer exactly -- and we found out WHY
Trained a per-reason-code Logistic Regression (same submodel structure
validated in Checkpoint 1) on train.csv, evaluated honestly on test.csv
(never touched during training or rule design) against the rule-based
scorer.py on the same test set:

Rule-based AUC: 0.6882
ML scorer AUC:  0.6882 (identical to 4 decimal places)

Rather than treat this as a disappointing null result, inspected the ML
model's actual learned coefficients directly. For item_not_received:
has_tracking_number=0.748, has_delivery_confirmation=0.903,
has_signature_confirmation=0.834 -- nearly equal, with no strong
preference for any one field. Traced this back to hidden_truth.py:
RELEVANT_FIELD_RATE_IF_LEGIT/NOT_LEGIT apply the SAME correlation
strength to every relevant field for a reason code, by design. There is
no hidden per-field weighting pattern in the data for ML to discover, so
an algorithm free to learn any weights converges to nearly the same
equal weighting we hand-picked in scorer.py's FIELD_WEIGHT = 1.0.

Per principle #2, keeping the rule-based scorer as primary since ML did
not measurably beat it. This is documented as a genuine, explained
finding, not an unexplained tie.


## Checkpoint 9

### FastAPI backend, verified to preserve safety behavior end-to-end
Built api.py with a single /score endpoint that calls scorer.py,
evidence.py, and policy.py directly -- zero business logic duplicated in
the API layer. Verified by actually running the server and sending real
HTTP requests (not just unit tests): the exact Checkpoint-3 dangerous
case (Rs 8,00,000 dispute with strong evidence) correctly returned
HUMAN REVIEW with the ceiling-exceeded reason message through the full
HTTP round trip, proving the API wrapper didn't accidentally
reimplement (and potentially weaken) the safety logic. Also added a
cross-check test comparing the API's evidence output directly against
calling evidence.assemble() in-process, to catch any future drift
between the two.

Small technical note: FastAPI's TestClient needs the `httpx` package
installed separately -- not automatically pulled in by fastapi itself.