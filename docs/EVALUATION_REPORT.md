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

| Strategy | Auto-Contest Share | Human-Review Share | Contested Precision | Realized Net Value | Cost & Penalty Assumptions |
|---|---:|---:|---:|---:|---|
| Contest Everything (Unconstrained) | 100.0% | 0.0% | 56.5% | **₹108.95 lakh** | Blind 100% contesting; ₹150 filing fee; assumes zero compliance penalties |
| Contest Everything (with Loss Penalty) | 100.0% | 0.0% | 56.5% | **₹18.64 lakh** | Documented Visa VAMP / Mastercard VFMP fine of $50 (₹4,150) per lost contest |
| **Live Policy (Automated-Only)** | 33.1% | 66.5% | 74.8% | **₹49.73 lakh** | Conservative automation: only high-confidence cases automated; reviewed cases valued at ₹0 |
| Live Policy + Human Review (Scenario a: Model Rate) | 33.1% | 66.5% | 56.5% | **₹108.09 lakh** | Reviewed cases recover at model calibrated win probability with ₹50 review fee |
| Live Policy + Human Review (Scenario b: Observed Rate) | 33.1% | 66.5% | 56.6% | **₹107.29 lakh** | Reviewed cases recover at observed held-out win rate (47.5%) with ₹50 review fee |
| **Theoretical Oracle Ceiling** | 100.0% | 0.0% | 100.0% | **₹109.00 lakh** | Bayes-optimal ceiling with hidden seller-legitimacy state access |

### Statistical Comparison & Break-Even Analysis

- **Bootstrap 95% Confidence Interval**:
  The difference between Live Policy (with review scenario b) and Contest Everything (unconstrained) is **-₹1.66 lakh (-₹165,622.71)** with bootstrap 95% CI **[-₹1.69 lakh, -₹1.62 lakh]** ([-₹169,104.28, -₹162,191.78]).
  The difference is entirely accounted for by the operational cost of human review (3,327 reviews × ₹50 = ₹166,350) minus ₹727.29 saved by accepting negative-EV disputes as losses. Even with zero review lift over raw baseline odds, the policy captures **98.48%** of Contest-Everything gross recovery while protecting merchant standing.

- **Break-Even Loss Penalty Level**:
  - **Raw Value Comparison**: Contest Everything (unconstrained) wins on raw unpenalized value (₹108.95L vs ₹49.73L automated-only, or ₹107.29L with review scenario b).
  - **Ranking Flip vs. Automated-Only**: Contest Everything falls below the Live Policy automated-only recovery (₹49.73L) when the penalty per lost contest exceeds **₹2,721.43** (if penalty applies to Contest Everything for entering monitoring) or **₹3,366.59** (if losing disputes in both are penalized). Both break-even thresholds are substantially below the documented minimum card-network monitoring penalty of **$50 per dispute (₹4,150)** under Visa VAMP / Mastercard VFMP.
  - **Ranking Flip vs. Policy with Review (Scenario b)**: Contest Everything falls below the Live Policy + Human Review when the penalty per lost contest on Contest Everything exceeds just **₹76.11**.


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
