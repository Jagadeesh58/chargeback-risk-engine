# Chargeback Risk Engine

[![CI](https://github.com/Jagadeesh58/chargeback-risk-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Jagadeesh58/chargeback-risk-engine/actions/workflows/ci.yml)

> **ML estimates risk. Evidence adds context. Economics measures value. Deterministic policy controls the financial action.**

Chargeback Risk Engine is an auditable decision system for evaluating chargeback disputes and deciding whether a case should be:

- `AUTO-CONTEST`
- `HUMAN-REVIEW`
- `ACCEPT-LOSS`

The system combines reason-code-aware risk scoring, evidence validation, relationship context, economic decisioning, bounded AI analysis, deterministic safety controls, and durable auditability.

**Live demo:** https://chargebackriskengine.streamlit.app/

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
merchant
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
> **Automation vs. Unconstrained Recovery**: The headline ₹49.73L realized net value reflects **conservative automated recovery only** (contesting ~33% of disputes with 74.8% precision, with the 59.9% of cases routed to `HUMAN-REVIEW` counted as ₹0 automated recovery). In contrast, an unconstrained contest-everything strategy recovers ₹108.95L because the fixed contest cost (₹150) is very low relative to dispute amounts (~₹4,000). The engine is explicitly tuned for safe, high-precision automation with human oversight rather than blind contesting. See [docs/WHY_NOT_CONTEST_EVERYTHING.md](docs/WHY_NOT_CONTEST_EVERYTHING.md) for detailed analysis of card-brand dispute monitoring programs (Visa VAMP / Mastercard VFMP), \$500 arbitration penalties, operational review staffing costs (`human_review_cost`), and payment processing termination risks.
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
