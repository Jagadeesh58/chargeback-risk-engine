# Evaluation Report

## Scope

The current evaluation uses the bundled synthetic chargeback dataset. No production Razorpay traffic, production credentials, or realized financial outcomes are used.

## Dataset

| Split | Rows |
|---|---:|
| Train | 20,000 |
| Dev | 5,000 |
| Held-out test | 5,000 |

Generation uses a fixed seed (`42`) and a deterministic 2/3, 1/6, 1/6 split. The held-out test set is used only after model selection is fixed.

## Selected model

Logistic Regression remains the live risk estimator. Model selection is performed on `dev.csv`; the held-out test set is used only for final reporting.

| Model | PR-AUC | Brier | Calibration error |
|---|---:|---:|---:|
| Rules | 0.7087 | 0.2302 | 0.1269 |
| Logistic Regression | 0.7234 | 0.2165 | 0.0075 |
| HGB challenger | 0.7254 | 0.2169 | 0.0130 |
| Offline hybrid challenger | 0.7266 | 0.2170 | 0.0244 |

## Candidate decision system

| Metric | Held-out result |
|---|---:|
| Auto-contest count | 1,492 |
| Auto-contest precision | 0.7593833780160858 |
| Auto-contest recall | 0.4012039660056657 |
| Human-review rate | 0.637 |
| Expected recovery | ₹4,831,124.763838673 |
| Expected contest cost | ₹223,800 |
| Expected net value | ₹4,607,324.763838673 |
| Synthetic false positives | 359 |

These are modeled expected values on synthetic data, not realized financial results.

## Frozen baseline comparison

The repository contains a frozen pre-change benchmark captured on the original 900-row evaluation set: expected net value ₹1,012,433.2567699989 and candidate uplift of approximately +2.95% / ₹29,927 on that original held-out comparison.

The original pre-change source archive itself is not included in the current repository snapshot, so a like-for-like re-execution of that frozen engine on the new 5,000-row test set cannot be reproduced here. The scaled candidate results above are therefore reported separately rather than presenting a made-up 5,000-row baseline comparison.

## Ablation

Ablation is generated automatically by `scripts/generate_report.py` on a fixed 500-row prefix of the held-out test set to keep the report generation fast. The full candidate benchmark and all headline candidate metrics use all 5,000 held-out rows.

## Review budget

| Review budget | Capacity | Precision | Recall | Recovered value |
|---:|---:|---:|---:|---:|
| 1% | 50 | 0.62 | 0.010977337110481586 | ₹241,742.87 |
| 5% | 250 | 0.58 | 0.051345609065155805 | ₹1,080,907.86 |
| 10% | 500 | 0.582 | 0.10304532577903683 | ₹2,029,957.33 |
| 20% | 1,000 | 0.534 | 0.18909348441926346 | ₹3,427,259.46 |

The review budget ranks cases in the existing HUMAN-REVIEW queue so limited analyst capacity can be allocated to higher-value cases.

## Calibration

Held-out Logistic Regression calibration error is `0.007541071429129429`. Calibration is fitted from `dev.csv` and evaluated on the held-out test set.

## Leakage checks

`python scripts/verify_no_leakage.py` passes. The best single evidence field AUC is 0.540 on the development split, while the reason-aware per-reason submodel reaches 0.691, with a +0.085 gap over the reason-code-blind model. The synthetic `would_win` label is not present in scorer inputs at decision time.

## Adversarial and safety evaluation

The focused command

```bash
python -m pytest -q tests/test_adversarial_suite.py tests/test_safety_regression.py
```

passes **27/27 tests**. Coverage includes prompt injection, missing and contradictory evidence, malformed input, duplicate/replay requests, amount manipulation, graph escalation, AI fallback behavior, policy boundaries, retry abuse, and monetary-ceiling bypass attempts.

## Latency

`python scripts/latency.py` measures the local end-to-end decision path with warm model artifacts and unique dispute IDs.

Current run:

- p50: 2.119985 ms
- p95: 2.438868 ms
- p99: 2.968378 ms
- max: 4.860749 ms

This is a local single-process measurement, not a production SLA.

## Audit and idempotency

The decision record stores the decision, policy/model versions, evidence, economics, graph signal, AI metadata, timestamp, and request ID. Audit integrity is verified by the repository test suite, and repeated dispute IDs replay the original decision context.

## Reproducibility

The main generated artifacts are:

- `artifacts/hard_cases_report.json`
- `artifacts/policy_profile.json`

The detailed verification report is generated locally by `make verify` and is intentionally not required to be tracked in Git.

The benchmark and report are generated from the repository's current synthetic data and code.
