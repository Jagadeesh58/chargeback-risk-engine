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