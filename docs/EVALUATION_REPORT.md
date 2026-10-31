# Evaluation Report

## Scope

The current evaluation uses the bundled synthetic chargeback dataset. No production payment-gateway traffic, production credentials, or realized financial outcomes are used.

## Dataset

| Split | Rows |
|---|---:|
| Train | 20,000 |
| Dev | 5,000 |
| Held-out test | 5,000 |

The data is generated with a fixed seed and kept in separate train/dev/test files. The held-out test set is not used for model fitting or policy-threshold selection.

## Model comparison

| Model | PR-AUC | Brier | Calibration error |
|---|---:|---:|---:|
| Rules | 0.7087 | 0.2302 | 0.1269 |
| Logistic Regression | 0.7234 | 0.2165 | 0.0075 |
| HGB challenger | 0.7254 | 0.2169 | 0.0130 |
| Offline hybrid challenger | 0.7266 | 0.2170 | 0.0244 |

Logistic Regression remains the live risk estimator. Challenger models are evaluated offline and do not have authority over the final decision. Note that machine learning provides modest lift over deterministic rules (0.723 vs 0.709 PR-AUC; 0.697 vs 0.695 ROC-AUC) because the synthetic data generator is fundamentally a noisy combination of evidence validity flags.

## Policy selection

The production-facing policy profile is selected from `dev.csv` only. The current frozen profile is:

- policy version: `policy-v5-dev-optimized`
- auto-contest threshold: `0.65`
- accept-loss threshold: `0.30`
- minimum evidence completeness: `0.50`
- contest cost: `₹150`
- objective: maximize expected net value subject to precision >= 0.72 and auto-contest rate <= 0.40

The selected profile is stored in `artifacts/policy_profile.json`.

## Candidate decision system

| Metric | Held-out result |
|---|---:|
| Auto-contest count | 1,657 |
| Auto-contest precision | 0.7483 |
| Auto-contest recall | 0.4391 |
| Human-review rate | 0.6654 |
| Expected recovery | ₹5,276,669.04 |
| Expected contest cost | ₹248,550.00 |
| Expected net value | ₹5,028,119.04 |
| Realized recovery | ₹5,221,442.86 |
| Realized net value | ₹4,972,892.86 |
| Synthetic false positives | 417 |

Expected values use the model's probability signal. Realized recovery/net value use the synthetic `would_win` label and are not production financial results.

**Conservative Automation Notice**: The headline realized net value of ₹49.73L reflects **conservative automated recovery only** (contesting ~33% of disputes with 74.8% precision). The 66.5% of disputes held for `HUMAN-REVIEW` are counted as ₹0 automated recovery. In comparison, an unconstrained "contest-everything" strategy across all 5,000 cases recovers ₹108.95L because the dispute fee (₹150) is small relative to the average dispute amount (~₹4,000). The engine is tuned to prioritize high automation precision and human oversight over unconstrained recovery.

## Comprehensive Strategy Comparison & Economic Trade-off Analysis

Evaluated on `data/test.csv` (5,000 held-out disputes) under identical operational cost assumptions (`CONTEST_COST = ₹150`, `HUMAN_REVIEW_COST = ₹50`).

| Strategy | Auto Share | Review Share | Contested Precision | Lost Contests | Net Value (p = 0) | Net Value (p = ₹4,150) | Strategy Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| **Contest Everything** | 100.0% | 0.0% | 56.5% | 2,176 | **₹108.95 lakh** | **₹18.64 lakh** | Blind 100% contesting; ₹150 filing fee; pays penalty on lost disputes |
| **Live Policy (Automated-Only)** | 33.1% | 66.5% | 74.8% | 417 | **₹49.73 lakh** | **₹32.42 lakh** | Conservative automation: high-confidence cases only; reviewed cases valued at ₹0 recovery |
| Live Policy + Human Review (Scenario a: Model Rate) | 33.1% | 66.5% | 56.5% | 2,170.4 | **₹108.09 lakh** | **₹18.02 lakh** | Reviewed cases contested at model expected win rate with ₹50 review fee (bound) |
| Live Policy + Human Review (Scenario b: Observed Rate) | 33.1% | 66.5% | 56.6% | 2,164 | **₹107.29 lakh** | **₹17.49 lakh** | Reviewed cases contested at observed held-out win rate with ₹50 review fee (bound) |
| **Theoretical Oracle Ceiling** | 97.2% | 0.0% | 57.5% | 2,065 | **₹109.00 lakh** | **₹23.30 lakh** | Unpenalized Bayes-optimal policy ceiling with hidden state access |

### Statistical Comparison & Break-Even Analysis

- **Raw Value Comparison (Unpenalized Baseline, $p=0$)**:
  Contest Everything (unconstrained) achieves the highest raw financial recovery (**₹108.95 lakh**) because the fixed contest cost (₹150) is very low relative to dispute amounts (~₹4,000). The Live Policy achieves **₹49.73 lakh** in conservative automated-only recovery (contesting 33.1% of cases with 74.8% precision) and **₹107.29 lakh** under review scenario b.

- **Bootstrap 95% Confidence Intervals (Resampling Disputes, N=1,000)**:
  1. **Live Policy (Automated-Only) vs. Contest Everything**:
     - At $p = 0$: difference is **-₹59.22 lakh (-₹5,921,836.94)** with 95% CI **[-₹62.01 lakh, -₹56.02 lakh]**.
     - At base-case $p = ₹4,150$: difference is **+₹13.78 lakh (+₹1,378,013.06)** with 95% CI **[+₹9.06 lakh, +₹19.05 lakh]**.
  2. **Live Policy (Scenario b) vs. Contest Everything**:
     - At $p = 0$: difference is **-₹1.66 lakh (-₹165,622.71)** with 95% CI **[-₹1.69 lakh, -₹1.62 lakh]**.
     - At base-case $p = ₹4,150$: difference is **-₹1.16 lakh (-₹115,822.71)** with 95% CI **[-₹1.43 lakh, -₹0.85 lakh]**.

- **Symmetric Break-Even Loss Penalty Level**:
  - **Ranking Flip vs. Automated-Only**: Contest Everything incurs 2,176 lost disputes whereas the Live Policy Automated-Only incurs only 417 (avoiding 1,759 losses). When a symmetric penalty per lost contest is applied to both strategies, Contest Everything falls below Live Policy Automated-Only when the penalty exceeds **₹3,366.59**. At the base-case sensitivity parameter of $p = ₹4,150$ (rupee modelling assumption), the Live Policy yields **₹32.42 lakh** vs Contest Everything's **₹18.64 lakh** (an advantage of **+₹13.78 lakh**).
  - **Ranking Flip vs. Policy with Review (Scenario b)**: In Scenario b, reviewed cases are contested, resulting in 4,984 contested disputes and 2,164 losses (avoiding only 12 losses relative to Contest Everything). Because it incurs ₹166,350 in human review costs and misses 4 wins, Contest Everything falls below Scenario b only if the loss penalty exceeds **₹13,801.89**. Scenarios a and b represent operational upper/lower bounds under full contestation, not proof of review lift.


## Historical pre-change comparison

A small frozen pre-change benchmark from the original 900-row evaluation snapshot is kept as `artifacts/baseline_benchmark.json`. Its expected net value was ₹1,012,433.26.

This historical snapshot is not treated as a like-for-like current 5,000-row benchmark. No unsupported current lift is claimed from it.

## Ablation

Ablation is generated automatically on the first 1,000 held-out rows to keep report generation practical. It compares rules-only, model-only, evidence-aware, economics-aware, graph-aware, and full-system variants without relabeling one pipeline as multiple systems.

## Review budget

The review-budget analysis ranks existing `HUMAN-REVIEW` cases so limited analyst capacity can be allocated to higher-value cases. The report stores the current budget curve generated by the repository code.

## Calibration

Held-out Logistic Regression calibration error is approximately `0.00754`. Calibration is fitted from `dev.csv` and evaluated on the held-out test set.

## Leakage checks

`python scripts/verify_no_leakage.py` checks that the evaluation label is not used as a live feature and reports single-field and reason-aware reference AUCs. The synthetic `would_win` label is never supplied to the live scorer.

## Adversarial and safety evaluation

The focused adversarial/safety suite covers prompt-injection-style case text, missing and contradictory evidence, malformed input, duplicate/replay requests, amount manipulation, graph escalation, AI fallback behavior, retry abuse, and monetary-ceiling bypass attempts.

## Latency

The current generated report records approximately:

- p50: 3.47 ms
- p95: 5.68 ms
- p99: 7.09 ms

This is a warm local single-process measurement with unique dispute IDs and is not a production SLA.

## Audit and idempotency

Decision records store the decision, policy/model versions, evidence, economics, graph context, request identifier, and audit metadata. The audit log uses a hash chain, and duplicate dispute IDs replay the durable decision.

## Reproducibility

Run the complete verification workflow with:

```bash
make verify
```

The workflow regenerates ignored benchmark/report outputs from the tracked source, data, and small public artifacts. The tracked public artifacts are intentionally limited to: `baseline_benchmark.json`, `hard_cases_report.json`, and `policy_profile.json`.

## Theoretical Oracle Ceiling

Computed via `scripts/oracle_ceiling.py` on `data/test.csv` (synthetic ground truth).

| Model | ROC-AUC | % of Ceiling (95% CI) | Chance-Adjusted Skill (Gini) | PR-AUC | % of Ceiling (95% CI) | Normalized PR Skill | Realized Net Value |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Oracle Ceiling** | **0.8156** | **100.0%** | **100.0%** | **0.7917** | **100.0%** | **100.0%** | **₹10,900,220.35** |
| Logistic (Live) | 0.6971 | 85.5% [83.9%, 87.4%] | 62.5% | 0.7234 | 91.4% [89.4%, 93.1%] | 69.9% | ₹10,895,685.42 |
| HGB Challenger | 0.6972 | 85.5% [83.8%, 87.4%] | 62.5% | 0.7254 | 91.6% [89.9%, 93.4%] | 70.8% | ₹10,895,802.59 |
| Hybrid Challenger | 0.6968 | 85.4% [83.8%, 87.4%] | 62.4% | 0.7266 | 91.8% [89.9%, 93.7%] | 71.3% | ₹10,895,714.02 |
| Rules Only | 0.6951 | 85.2% [83.6%, 87.2%] | 61.8% | 0.7087 | 89.5% [87.7%, 91.5%] | 63.4% | ₹10,879,407.59 |

**Methodological Notes**:
1. **Net Value Column**: All models land within 0.2% of each other on unconstrained net value (~₹108.8L to ₹109.0L). Because the fixed dispute cost is only ₹150 while disputes average ₹4,000, contesting everything recovers 99.95% of oracle value. Therefore, net value under unconstrained contesting cannot distinguish model predictive quality; models must be evaluated on PR-AUC and ROC-AUC.
2. **Chance-Adjusted Skill**: Because ROC-AUC 0.5 represents random chance, the raw ratio (85.5%) overstates skill. Chance-adjusted normalized Gini skill is `(0.6971 - 0.5) / (0.8156 - 0.5) = 62.5%`. Similarly, for PR-AUC with positive base rate 0.565, normalized skill is `(0.7234 - 0.565) / (0.7917 - 0.565) = 69.9%`.
3. **Observability Limit**: The remaining gap to the oracle ceiling cannot be crossed without direct access to the hidden seller legitimacy state, which is unobservable in live transaction data.

## AI Analyst Safety Evaluation

Evaluated against the bounded adversarial test suite in `tests/test_ai_analyst_evaluation.py`:
- Rejection rate on invalid/adversarial claims: 100%
- Fallback rate on malformed/unreachable API: 100%
- Hallucination-catch rate (invented/contradictory evidence): 100%
- Safety Invariant: The AI analyst can never alter final financial actions, routing scores, or policy decisions.
