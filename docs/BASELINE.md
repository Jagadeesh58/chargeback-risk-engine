# Frozen baseline

The baseline is the repository state captured before the candidate changes. It was executed from the original implementation associated with commit `086572fdd5549a8ba07f9a885d39e0e65b68ca28`.

## Baseline execution

**Observed:**

- Python: 3.13.5
- tests: 124 passed
- test duration: 4.01 s
- train/dev/test: 4,200 / 900 / 900 rows

The supplied pre-change source archive is retained as the immutable baseline input. Its SHA-256 is `f19bf0ef249b74b2e861a15fef3a258536e1c70369581701946a65235ffdc09a`. The original working tree was already dirty relative to its Git commit, so this archive hash is the source-snapshot identity used for the frozen baseline.

## Baseline model metrics

The original `artifacts/model_evaluation.json` is preserved as `artifacts/baseline_model_evaluation.json` so the pre-change measurements cannot be overwritten by candidate training.

Key held-out results:

| Model | ROC-AUC | PR-AUC | Brier | Calibration error |
|---|---:|---:|---:|---:|
| Rules | 0.6882 | 0.7093 | 0.2365 | 0.1246 |
| Logistic Regression | 0.6895 | 0.7401 | 0.2204 | 0.0342 |
| HGB | 0.6692 | 0.7118 | 0.2288 | 0.0911 |
| Hybrid | 0.6873 | 0.7279 | 0.2222 | 0.0480 |

## Frozen current-engine benchmark

Measured by executing the original pre-change engine on the same 900 held-out test cases:

- auto-contest: 310
- precision: 0.7290
- recall: 0.4449
- F1: 0.5526
- human-review rate: 0.4989
- expected recovery: ₹1,058,933
- expected contest cost: ₹46,500
- expected net value: ₹1,012,433
- synthetic false positives: 84

These monetary values are modeled expected values from synthetic data, not realized recovery.

## Integrity artifacts

`artifacts/baseline_manifest.json` records the baseline source-archive hash, commit, runtime/dependency versions, dataset hashes, model-artifact hashes, and frozen system benchmark.

## Historical Candidate Evolution & Provenance Hardening Note

In early iterations of the candidate decision engine on 5,000 synthetic test cases, the system permitted auto-contesting of 2,133 cases with ~72.9% precision. Following the implementation of strict fail-closed evidence provenance (`TRUSTED_SOURCES` validation and mandatory timestamp freshness windows), disputes with unverified or unannotated evidence fields are deterministically diverted to `HUMAN-REVIEW`. This reduces automated contesting to 1,324 cases (26.5% auto share) while increasing automated precision to 77.6% (reducing synthetic false-positive lost contests from 578 down to 297). This intentional trade-off reflects production financial safety: when evidence integrity cannot be proven, the engine fails closed to human review rather than risking automated loss fines and dispute monitoring escalation.
