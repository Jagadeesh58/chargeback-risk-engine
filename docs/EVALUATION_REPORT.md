# Evaluation Report

## Scope

All reported evaluation results are generated from the repository's synthetic dataset. No production Razorpay traffic, live transactions, or production credentials are used.

## Dataset

- train: 4,200 rows
- dev: 900 rows
- test: 900 rows
- fixed random seed: 42 in the learned models

Ground-truth labels are not changed by the evaluation scripts. The development split is used for model selection. The held-out test set is frozen and used only for final comparison/reporting.

## Model metrics

| Model | ROC-AUC | PR-AUC | Precision | Recall | F1 | Brier | Calibration error |
|---|---:|---:|---:|---:|---:|---:|---:|
| Rules baseline | 0.6882 | 0.7093 | 0.7080 | 0.6063 | 0.6532 | 0.2365 | 0.1246 |
| Live Logistic Regression | 0.6882 | 0.7316 | 0.7235 | 0.5098 | 0.5982 | 0.2206 | 0.0337 |
| HGB challenger | 0.6692 | 0.7118 | 0.7398 | 0.4980 | 0.5953 | 0.2288 | 0.0911 |
| Offline hybrid challenger | 0.6871 | 0.7300 | 0.7194 | 0.5551 | 0.6267 | 0.2222 | 0.0475 |

### Model selection

**Observed:** selection is performed on `dev.csv` only. The live Logistic Regression scorer wins the development comparison under the deterministic selection rule: highest PR-AUC, then lower Brier score and calibration error among near-tied candidates, then simpler implementation. The `test.csv` results below are final evaluation only.

HGB and the offline weighted hybrid remain evaluation challengers only. The rule scorer remains a baseline/safety signal.

## Frozen baseline vs candidate system benchmark

The frozen baseline was executed from the original pre-change implementation before candidate modifications. Both baseline and candidate are evaluated on the same held-out 900 cases.

| Strategy | Auto | Precision | Recall | F1 | Human review | Expected recovery | Expected loss | Expected contest cost | Expected net value |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Always contest | 900 | 0.5644 | 1.0000 | 0.7216 | 0.0000 | ₹2,151,161 | ₹1,138,839 | ₹135,000 | ₹2,016,161 |
| Always accept | 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | ₹0 | ₹3,789,798 | ₹0 | ₹0 |
| Rules only | 372 | 0.7043 | 0.5157 | 0.5955 | 0.3956 | ₹1,304,925 | ₹1,450,875 | ₹55,800 | ₹1,249,125 |
| Logistic only | 345 | 0.7188 | 0.4882 | 0.5815 | 0.5389 | ₹1,094,110 | ₹1,657,140 | ₹51,750 | ₹1,042,360 |
| Baseline current engine | 310 | 0.7290 | 0.4449 | 0.5526 | 0.4989 | ₹1,058,933 | ₹2,730,864 | ₹46,500 | ₹1,012,433 |
| Chargeback Sentinel | 345 | 0.7188 | 0.4882 | 0.5815 | 0.5389 | ₹1,094,110 | ₹1,657,140 | ₹51,750 | ₹1,042,360 |

**Observed:** Candidate expected net value is approximately ₹29,927 higher than the frozen current engine, or +2.95%, on this synthetic held-out set. Candidate auto-contest count is 35 higher, recall is 4.33 percentage points higher, precision is 1.02 percentage points lower, and human-review rate is 4.00 percentage points higher.

Expected loss is the synthetic disputed amount minus modeled expected recovery; contest cost is reported separately. Expected loss is the synthetic disputed amount minus modeled expected recovery; contest cost is reported separately. These monetary figures are **EXPECTED** values from the repository's model estimate and flat cost assumptions. They are not realized financial outcomes.

## Counterfactuals

The counterfactual engine performs a bounded single-field search over relevant case inputs and reruns the same canonical decision path. It does not change production audit state, model weights, thresholds, or external systems.

Current deterministic demo examples show both:

- a case where risk changes but the final action stays the same
- a case where one valid evidence change flips `AUTO-CONTEST` to `HUMAN-REVIEW`

## Adversarial and safety evaluation

The candidate suite contains 16 focused safety/adversarial regression tests covering:

- malicious text/prompt injection in extra evidence input
- missing evidence
- `UNKNOWN` evidence
- contradictory evidence
- invalid evidence
- malformed IDs
- unknown reason codes
- duplicate requests
- monetary ceiling bypass
- high-confidence weak-evidence cases
- low-confidence strong-evidence cases
- impossible evidence combinations
- graph escalation
- contest retry limit
- ML/policy separation

## Leakage

The leakage script reports:

- best single input field AUC: 0.549
- reason-aware submodel AUC: 0.691
- blind reason baseline AUC: approximately 0.586
- reason-aware gap: approximately +0.104

**Observed:** the target label is not directly exposed through an individual feature.

## Chronological ordering check

The repository includes a chronological ordering check using the synthetic dates. It is explicitly labeled as a **chronological ordering check**, not temporal robustness evidence. The generated dates do not establish a real production time distribution or drift process.

## Calibration

`calibration.py` retains an informational calibration curve for the legacy rule score. It is not substituted into the deterministic policy threshold, which continues to use the live Logistic Regression estimate.

## Latency

The timing gate warms the live model and measures 300 unique requests through `decide_case(...)` with a temporary audit database.

Reported label:

**LOCAL END-TO-END DECISION LATENCY**

Current observed values from `scripts/latency.py`:

- p50: 1.802171 ms
- p95: 2.184858 ms
- p99: 2.325221 ms

This is a local single-process measurement, not a production throughput or SLA claim.

## Reproducibility

The important artifacts record model, feature, policy, dataset and runtime information where applicable. Learned models use a fixed random seed. The frozen baseline source archive and benchmark are retained separately from candidate evaluation so the pre-change comparison is not regenerated from modified code.
