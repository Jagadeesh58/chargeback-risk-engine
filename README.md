# Chargeback Risk Engine

[![CI](https://github.com/Jagadeesh58/chargeback-risk-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Jagadeesh58/chargeback-risk-engine/actions/workflows/ci.yml)

Chargeback disputes cost online merchants over \$100B annually in lost revenue, bank fines, and manual triage costs. This engine automates high-confidence dispute representments while strictly enforcing deterministic safety policy, card network dispute limits, and cryptographic audit trails.

**Live demo:** https://chargebackriskengine.streamlit.app/ | **Key Decisions:** [docs/DECISIONS.md](docs/DECISIONS.md) | **Economics Deep Dive:** [docs/WHY_NOT_CONTEST_EVERYTHING.md](docs/WHY_NOT_CONTEST_EVERYTHING.md)

---

### Strategy Comparison

| Dimension | Naive Baseline (Rules / Manual) | Always-Contest (Spreadsheet Strategy) | Chargeback Risk Engine (This System) |
|---|---|---|---|
| **Action Selection** | Static heuristic rules | Blind 100% automated contest | **Deterministic policy gating calibrated ML** |
| **Representment Win Rate** | ~50.2% baseline | ~50.2% (submits weak/failed claims) | **74.8% high-precision automation** |
| **Card Network Standing** | Unmanaged dispute ratio | Severe risk of Visa VAMP / Mastercard VFMP bans | **Protected (monitors dispute hygiene & limits)** |
| **Arbitration Risk** | Sporadic | Extreme (\$500 non-refundable network fee on loss) | **Shielded by strict evidence completeness gates** |
| **Operational Impact** | Heavy manual triage | Zero oversight; catastrophic compliance fines | **Automates 33.1%, routes 66.5% to review, accepts 0.3% loss** |
| **Auditability** | Ephemeral application logs | Mutable database records | **Tamper-evident SHA-256 hash-chained ledger** |

---

### 30-Second Quickstart

```bash
# 1. Clone repository and install dependencies
git clone https://github.com/Jagadeesh58/chargeback-risk-engine.git
cd chargeback-risk-engine
pip install -r requirements.txt

# 2. Run test suite & verify release criteria
pytest -q
python scripts/verify_release.py

# 3. Launch interactive Streamlit demo or API
streamlit run scripts/demo.py
# or launch REST API: uvicorn chargeback_risk_engine.api:app --port 8000
```

---

### Key Evaluation Snapshot

*(Evaluated on 5,000 held-out synthetic test disputes; synthetic evaluation only, not a production performance guarantee)*

| Metric | Result |
|---|---:|
| PR-AUC | **0.7234** |
| Auto-contest precision | **74.8%** |
| Auto-contest recall | **43.9%** |
| Realized net value | **₹49.73 lakh (synthetic-only)** |
| Selected policy threshold | **0.65** from `dev.csv` |
| P95 local latency | **5.68 ms** |
| Hard cases | **8 / 8 passed** |

> [!NOTE]
> **Automation vs. Unconstrained Recovery**: The headline ₹49.73L realized net value reflects **conservative automated recovery only** (contesting ~33% of disputes with 74.8% precision, with the 66.5% of cases routed to `HUMAN-REVIEW` counted as ₹0 automated recovery). In contrast, an unconstrained contest-everything strategy recovers ₹108.95L because the fixed contest cost (₹150) is very low relative to dispute amounts (~₹4,000). The engine is explicitly tuned for safe, high-precision automation with human oversight rather than blind contesting. See [docs/WHY_NOT_CONTEST_EVERYTHING.md](docs/WHY_NOT_CONTEST_EVERYTHING.md) for detailed analysis of card-brand dispute monitoring programs (Visa VAMP / Mastercard VFMP), \$500 arbitration penalties, operational review staffing costs (`human_review_cost`), and payment processing termination risks.


### Comprehensive Strategy Comparison & Economic Trade-off Analysis

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


---

### What This Project Is NOT

- **NOT an Unconstrained Auto-Responder:** It does NOT blindly contest every dispute. Submitting weak representments triggers card network fines (\$50–\$100/dispute) and payment processor termination.
- **NOT a Payment Gateway:** It does NOT process credit cards, hold merchant funds, or initiate payment capture.
- **NOT an LLM Financial Decision-Maker:** LLMs and ML models **only provide advisory signals**. They are strictly forbidden from choosing financial actions (`AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS`). Only deterministic Python policy decides financial actions.

---

## Why this design

Financial workflows should not allow an AI model or LLM to directly authorize a money-moving action.

This project therefore uses a **bounded-automation architecture**:

```text
                         ┌──────────────────┐
                         │  Dispute Input   │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │    Risk Model    │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Evidence Scoring │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Relationship /   │
                         │   Graph Context  │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │    Economics     │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Bounded AI       │
                         │ Evidence Analyst │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Deterministic    │
                         │     Policy       │
                         └────────┬─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
             AUTO-CONTEST   HUMAN-REVIEW   ACCEPT-LOSS
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Durable Audit &  │
                         │    Idempotency   │
                         └──────────────────┘
```

### Safety boundary

The ML model, graph analysis, economics layer, and AI analyst provide **signals and explanations**.

Only the deterministic policy layer can select the final financial action.

The AI analyst cannot:

- change policy thresholds
- bypass safety gates
- authorize an `AUTO-CONTEST`
- increase monetary limits
- execute an external chargeback

---

## Core capabilities

### 1. Reason-code-aware risk scoring

The system supports reason-code-specific decisioning instead of treating every dispute identically.

The risk scorer produces a calibrated estimate of the probability that a dispute would be won if contested.

### 2. Evidence verification

Evidence is evaluated against the requirements for the selected reason code.

Evidence is explicitly represented as:

```text
True   → supporting evidence
False  → contradictory / negative evidence
None   → unknown / unavailable evidence
```

Unknown evidence is not silently converted into positive evidence.

### 3. Relationship and network context

A deterministic relationship graph tracks contextual relationships such as:

```text
customer
device
IP address
card fingerprint
related disputes
```

This layer can provide additional risk context and escalation signals.

The graph is intentionally treated as a deterministic risk-context component rather than being presented as a separately validated learned model.

### 4. Economic decisioning

The system evaluates whether contesting a dispute is economically worthwhile.

The policy considers factors such as:

```text
win probability
dispute amount
contest cost
expected recovery
safety limits
review constraints
```

This allows the system to distinguish between:

```text
"the case may be winnable"
```

and:

```text
"contesting the case is actually worthwhile and permitted"
```

### 5. Bounded AI evidence analyst

The optional AI analyst can:

- summarize evidence
- identify missing evidence
- identify contradictions
- suggest evidence-grounded dispute arguments

AI output is advisory only.

The financial decision remains controlled by deterministic policy.

### 6. Counterfactual explanation

For supported decisions, the system can explain what change in the case would be sufficient to alter the outcome.

Counterfactuals are treated as **read-only simulations** and are never persisted as real disputes.

### 7. Durable audit trail

Each decision records auditable state including:

- request identifier
- dispute identifier
- model version
- policy version
- decision
- evidence summary
- economic result
- explanation
- audit metadata

Duplicate requests can replay the original durable decision.

---

## Safety controls

The implementation includes deterministic controls for:

- contradictory evidence
- unknown evidence
- monetary ceilings
- duplicate request handling
- replay protection
- untrusted case notes
- prompt-injection-style text
- AI-service failure
- counterfactual isolation
- graph-based escalation
- audit integrity

A critical design rule is:

```text
AI can recommend.
Policy decides.
```

See:

- [`SECURITY.md`](SECURITY.md)
- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)

---

## Evaluation

The repository includes a reproducible synthetic evaluation dataset with separate train, development, and held-out test splits.

| Split | Rows |
|---|---:|
| Train | 20,000 |
| Development | 5,000 |
| Held-out test | 5,000 |

The intended evaluation lifecycle is:

```text
TRAIN
  │
  ▼
MODEL FIT
  │
  ▼
DEV
  │
  ├── calibration
  ├── policy tuning
  └── threshold selection
  │
  ▼
FROZEN POLICY
  │
  ▼
HELD-OUT TEST
  │
  ├── precision
  ├── recall
  ├── PR-AUC
  ├── expected value
  ├── false-positive cost
  └── calibration
```

### Current evaluation snapshot

The current public evaluation snapshot reports approximately:

| Metric | Result |
|---|---:|
| PR-AUC | **0.7234** |
| Auto-contest precision | **74.8%** |
| Auto-contest recall | **43.9%** |
| Realized net value | **₹49.73 lakh (synthetic-only)** |
| Selected policy threshold | **0.65** from `dev.csv` |
| P95 local latency | **5.68 ms** |
| Hard cases | **8 / 8 passed** |

These are **synthetic evaluation results** and are not production-performance guarantees.

The operating point intentionally prioritizes safe automation over maximizing automatic contest recall.

> [!NOTE]
> **Automation vs. Unconstrained Recovery**: The headline ₹49.73L realized net value reflects **conservative automated recovery only** (contesting ~33% of disputes with 74.8% precision, with the 66.5% of cases routed to `HUMAN-REVIEW` counted as ₹0 automated recovery). In contrast, an unconstrained contest-everything strategy recovers ₹108.95L because the fixed contest cost (₹150) is very low relative to dispute amounts (~₹4,000). The engine is explicitly tuned for safe, high-precision automation with human oversight rather than blind contesting. See [docs/WHY_NOT_CONTEST_EVERYTHING.md](docs/WHY_NOT_CONTEST_EVERYTHING.md) for detailed analysis of card-brand dispute monitoring programs (Visa VAMP / Mastercard VFMP), \$500 arbitration penalties, operational review staffing costs (`human_review_cost`), and payment processing termination risks.
>
> **Skill vs. Chance**: Against the theoretical oracle ceiling (PR-AUC 0.7917, ROC-AUC 0.8156), the live Logistic model captures 85.5% of raw ROC-AUC (62.5% chance-adjusted Gini skill above chance) and 91.4% of raw PR-AUC (69.9% normalized skill above base rate). Machine learning provides modest lift over rules (0.723 vs 0.709 PR-AUC) because synthetic ground truth is generated from noisy evidence rules.

---

## Evaluation methodology

The repository includes separate checks for:

- rules-only baseline
- model-only baseline
- evidence-aware decisioning
- economics-aware decisioning
- graph-aware decisioning
- full-system decisioning
- threshold sensitivity
- calibration
- review-budget optimization
- hard-case verification
- latency
- adversarial/safety behavior
- audit integrity
- leakage checks
- stress scenarios

### Graph evaluation note

The bundled tabular dataset does not contain the historical relationship identifiers required for a clean held-out graph-performance comparison.

Therefore graph behavior is evaluated separately through deterministic graph scenarios and safety tests rather than claiming an unsupported tabular performance lift.

---

## Running the project

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run the test suite

```bash
python -m pytest -q
```

### Run complete verification

```bash
make verify
```

The verification workflow uses the tracked frozen policy profile. To deliberately
reselect a policy from `dev.csv`, run:

```bash
make policy-optimize
```

### Generate/rebuild synthetic data

```bash
make data
```

### Run benchmark

```bash
make benchmark
```

### Run hard cases

```bash
make hard-cases
```

### Run latency measurement

```bash
make latency
```

Benchmark across database scales (`python scripts/latency.py`):

| SQLite History Scale | Runs | P50 Latency | P95 Latency | Subgraph Traversal |
|---|---:|---:|---:|---|
| Clean DB | 50 | 30.5 ms | 35.7 ms | 0 rows loaded |
| 100 historical rows | 50 | 32.5 ms | 109.3 ms | $\le 2$-hop indexed subgraph |
| 1,000 historical rows | 50 | 34.5 ms | 44.3 ms | $\le 2$-hop indexed subgraph |
| 10,000 historical rows | 50 | 34.9 ms | 53.4 ms | $\le 2$-hop indexed subgraph |
| 50,000 historical rows | 25 | 32.6 ms | 41.0 ms | $\le 2$-hop indexed subgraph |

*Measured locally with unique dispute IDs per request. Indexed lookup on `graph_entities(entity_type, entity_value)` with hub degree capping ($\le 20$) keeps decision latency flat and isolated from table growth.*

---

## Streamlit application

Start the dashboard with:

```bash
streamlit run apps/app_deployed.py
```

The dashboard provides:

- live dispute scoring
- reason-code selection
- evidence selection
- decision waterfall
- expected-value display
- relationship-risk context
- bounded AI evidence analysis
- counterfactual explanation
- audit information
- deterministic demonstration cases

### Demo cases

The dashboard includes deterministic scenarios covering:

1. strong supporting evidence
2. mixed / incomplete evidence
3. relationship-network escalation
4. weak evidence
5. economic boundary behavior

See [`DEMO.md`](DEMO.md).

---

## API

Start the API with:

```bash
uvicorn apps.api:app --reload
```

Primary endpoint:

```text
POST /decision
```

Compatibility endpoint:

```text
POST /score
```

The API and local execution path use the same canonical decision engine.

---

## Repository structure

```text
chargeback-risk-engine/
│
├── apps/
│   ├── api.py
│   └── app_deployed.py
│
├── chargeback_risk_engine/
│   ├── engine/
│   │   ├── hybrid_pipeline.py
│   │   ├── risk_graph.py
│   │   ├── counterfactual.py
│   │   └── decision_result.py
│   │
│   ├── monitoring/
│   │   └── drift_guard.py
│   │
│   ├── ai_analyst.py
│   ├── audit_log.py
│   ├── calibration.py
│   ├── evidence.py
│   ├── metrics.py
│   ├── ml_scorer.py
│   ├── policy.py
│   ├── policy_optimizer.py
│   ├── policy_profile.py
│   └── gateway_adapter.py
│
├── data/
│   ├── train.csv
│   ├── dev.csv
│   └── test.csv
│
├── docs/
│   ├── BASELINE.md
│   ├── EVALUATION_PROTOCOL.md
│   ├── EVALUATION_REPORT.md
│   ├── FINAL_VERIFICATION.md
│   ├── MODEL_CARD.md
│   └── THREAT_MODEL.md
│
├── scripts/
│   ├── benchmark.py
│   ├── demo.py
│   ├── evaluate_hard_cases.py
│   ├── external_benchmark.py
│   ├── generate_data.py
│   ├── generate_report.py
│   ├── latency.py
│   ├── sensitivity.py
│   ├── stress_benchmark.py
│   ├── verify_no_leakage.py
│   └── verify_release.py
│
├── tests/
│
├── artifacts/
│   ├── hard_cases_report.json
│   └── policy_profile.json
│
├── ARCHITECTURE.md
├── CONTRIBUTING.md
├── DATA_DICTIONARY.md
├── DEMO.md
├── SECURITY.md
├── Makefile
├── pyproject.toml
└── requirements.txt
```

---


## What goes beyond a basic scorer

This repository implements safety-critical architectural controls beyond tabular probability scoring:

1. **Deterministic Safety Authority**: The AI analyst and ML models provide signals only. Only deterministic policy can select financial actions (enforced by `tests/test_ai_analyst_evaluation.py` and `tests/test_safety_regression.py`).
2. **Cryptographic Audit Log**: Every decision is persisted in a local SQLite hash chain using SHA-256 links, guaranteeing tamper evidence and idempotent decision replays.
3. **Actionable Counterfactuals**: Evaluates single-change evidence reversals (checking actionable flips from missing/unconfirmed to confirmed) to explain what evidence would flip an adverse decision without promising joint-flip optimality.
4. **Distribution Drift Guard**: Continuous monitoring of incoming feature distributions and output risk scores.
5. **Operational Review-Budget Optimizer**: Knapsack optimization that prioritizes human-review capacity toward maximum marginal financial recovery.
6. **Leakage Verification Tooling**: Enforces strict separation between ground-truth training variables and live runtime features.
7. **API Hardening & Model Integrity**: Constant-time API-key verification (`hmac.compare_digest`), request payload limits (413), rate limiting (429), and SHA-256 sidecar model hash verification before deserialization.

## Testing

The test suite covers the decision engine and its supporting components, including:

- API behavior
- local pipeline behavior
- evidence handling
- policy rules
- economic decisioning
- ML scoring
- calibration
- sensitivity analysis
- graph behavior
- counterfactuals
- audit integrity
- idempotency
- adversarial safety cases
- hard cases
- drift monitoring
- stress scenarios
- Payment‑gateway adapter behavior
- dashboard data dependencies

Run:

```bash
python -m pytest -q
```

The exact passing test count is intentionally not treated as a permanent architectural claim; use the current local/CI result as the authoritative count.

---

## Data and leakage

The bundled data is synthetic and is included to make the project reproducible.

The label `would_win` is evaluation/training ground truth and is never supplied to the live decision path.

The repository includes leakage verification tooling:

```bash
python scripts/verify_no_leakage.py
```

See:

- [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md)
- [`docs/EVALUATION_PROTOCOL.md`](docs/EVALUATION_PROTOCOL.md)
- [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md)

---

## Security model

The project intentionally separates:

```text
Untrusted input
      ↓
Structured evidence
      ↓
Risk / graph / economics / AI signals
      ↓
Deterministic safety policy
      ↓
Allowed action
```

Case notes and AI-generated content cannot directly select the final financial action.

For the complete security contract, see [`SECURITY.md`](SECURITY.md).

---

## Limitations

### Synthetic benchmark

The bundled dataset is synthetic.

It should not be interpreted as a representation of production payment traffic or chargeback distribution.

### Predictive-performance claims

The published metrics are evaluation-snapshot results.

They are not guarantees of production precision, recall, recovery, or financial savings.

### Graph validation

Relationship context is validated separately from the tabular benchmark because the required historical relationship features are not present in the bundled evaluation data.

### AI dependency

The AI analyst is optional.

When no external AI service is configured, the core decision flow can continue using deterministic fallback behavior.

### Production status

This repository is a buildathon/research prototype.

A production deployment would require additional:

- security review
- operational monitoring
- model validation
- data-governance controls
- access controls
- service isolation
- reliability testing
- production integration testing

---

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system architecture and decision flow
- [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) — dataset and field definitions
- [`DEMO.md`](DEMO.md) — dashboard and deterministic demo flow
- [`SECURITY.md`](SECURITY.md) — security and safety contract
- [`docs/BASELINE.md`](docs/BASELINE.md) — baseline methodology
- [`docs/EVALUATION_PROTOCOL.md`](docs/EVALUATION_PROTOCOL.md) — evaluation design
- [`docs/EVALUATION_REPORT.md`](docs/EVALUATION_REPORT.md) — evaluation results
- [`docs/FINAL_VERIFICATION.md`](docs/FINAL_VERIFICATION.md) — release verification
- [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md) — model scope and limitations
- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — threat analysis

---

## Project status

An auditable chargeback-dispute decision system combining machine learning, evidence assembly, risk graphs, and deterministic policy.

This repository demonstrates an auditable, safety-bounded chargeback decision workflow in which automated financial actions remain under deterministic control.
