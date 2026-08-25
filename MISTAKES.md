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