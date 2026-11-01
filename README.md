# Chargeback Risk Engine

[![CI](https://github.com/username/chargeback-risk-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/username/chargeback-risk-engine/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Status**: Reference implementation evaluated on synthetic data only. Not validated on real payment outcomes. Not legal or compliance advice.

Auditable, evidence-aware chargeback dispute decision system where machine learning and heuristic models provide advisory signals, while a deterministic policy alone routes financial actions (`AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS`). All monetary values and evaluations are synthetic.

```mermaid
flowchart LR
    A[Dispute Payload] --> B[Advisory Signals<br/>ML · Evidence · Graph · Context]
    B --> C[Authoritative Boundary<br/>policy.decide]
    C --> D[AUTO-CONTEST]
    C --> E[HUMAN-REVIEW]
    C --> F[ACCEPT-LOSS]
    C --> G[(SQLite WAL Store<br/>SHA-256 Hash Chain)]
```

---

## 60-Second Quickstart

```bash
# 1. Clean environment install
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Start API server in development mode
CHARGEBACK_ENV=development uvicorn chargeback_risk_engine.api:app --host 127.0.0.1 --port 8000

# 3. Authenticated decision request with fail-closed evidence provenance
curl -s -X POST http://127.0.0.1:8000/decision \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-api-key" \
  -d @examples/request_verified.json
```

---

## Deterministic Decision Rules

Financial actions are chosen strictly by `chargeback_risk_engine.policy.decide()` using thresholds frozen in `artifacts/policy_profile.json`:

| Action | Gate Criteria Required | Operational Rationale |
|---|---|---|
| **AUTO-CONTEST** | Win probability ≥ 0.65<br/>• Evidence completeness ≥ 0.50 (0 unverified fields)<br/>• Graph risk < 0.60<br/>• Amount ≤ ₹50,000 (configurable internal parameter)<br/>• Expected Net Value > 0 (after configurable ₹150 filing fee) | High-probability, evidenced claims automated for recovery without merchant operational overhead. |
| **HUMAN-REVIEW** | Ambiguous probability (0.30 < p < 0.65)<br/>• Missing or unverified evidence provenance<br/>• Network graph risk ≥ 0.60<br/>• Amount > ₹50,000 (configurable ceiling) | Protects against false rejections, dispute penalties, and edge cases requiring human review. |
| **ACCEPT-LOSS** | Win probability ≤ 0.30 **AND** Expected Net Value ≤ 0 | Low-probability disputes where contesting cost (₹150) exceeds expected recovery. |

---

## Configuration Reference

Runtime configuration via environment variables (`Settings` class):

| Variable | Default | Production Requirement |
|---|---|---|
| `CHARGEBACK_ENV` | `production` | Set to `production` (enforces strict security gates; use `development` for local testing). |
| `CHARGEBACK_API_KEY` | `""` | Mandatory 32+ character secret token in production mode. |
| `CHARGEBACK_API_KEYS` | `""` | Optional comma-separated multi-actor credentials (`id:secret:role`). |
| `CHARGEBACK_METRICS_KEY` | `""` | Optional dedicated token for `/metrics` in production mode. |
| `CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE` | `false` | Must remain `false` in production (ignored/overridden to enforce provenance). |
| `CHARGEBACK_AUDIT_DB_PATH` | `<root>/audit_log.db` | Absolute path outside package directory with persistent storage. |
| `CHARGEBACK_MODEL_PATH` | `<artifacts>/ml_scorer_model.json` | Path to valid model weights with corresponding `.sha256` sidecar file. |
| `CHARGEBACK_CORS_ORIGINS` | `http://localhost:3000...` | Explicit allowed origins (wildcards like `*` are rejected in production). |
| `CHARGEBACK_RATE_LIMIT` | `60` | In-memory requests/minute limit per client key (tunable). |
| `CHARGEBACK_REQUEST_TIMEOUT_SECONDS` | `5.0` | Maximum request execution window in seconds. |

---

## Key Evaluation Snapshot

*(Evaluated on 5,000 held-out synthetic disputes from `data/test.csv`; synthetic data circular by construction, not a real financial guarantee)*

| Metric | Result |
|---|---:|
| PR-AUC | **0.7234** |
| Auto-contest precision | **77.6%** |
| Auto-contest recall | **36.4%** |
| Realized net value | **₹41.09 lakh (synthetic-only)** |
| Selected policy threshold | **0.65** from `dev.csv` |

---

## Comprehensive Strategy Comparison & Economic Trade-off Analysis

Evaluated on `data/test.csv` (5,000 held-out disputes) under identical operational cost assumptions (`CONTEST_COST = ₹150`, `HUMAN_REVIEW_COST = ₹50`).

| Strategy | Auto Share | Review Share | Contested Precision | Lost Contests | Net Value (p = 0) | Net Value (p = ₹4,150) | Strategy Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| **Contest Everything** | 100.0% | 0.0% | 56.5% | 2,176 | **₹108.95 lakh** | **₹18.64 lakh** | Blind 100% contesting; ₹150 filing fee; pays penalty on lost disputes |
| **Live Policy (Automated-Only)** | 26.5% | 73.2% | 77.6% | 297 | **₹41.09 lakh** | **₹28.77 lakh** | Conservative automation: high-confidence cases only; reviewed cases valued at ₹0 recovery |
| Live Policy + Human Review (Scenario a: Model Rate) | 26.5% | 73.2% | 56.6% | 2,165.2 | **₹108.22 lakh** | **₹18.36 lakh** | Reviewed cases contested at model expected win rate with ₹50 review fee (bound) |
| Live Policy + Human Review (Scenario b: Observed Rate) | 26.5% | 73.2% | 56.6% | 2,164 | **₹107.12 lakh** | **₹17.32 lakh** | Reviewed cases contested at observed held-out win rate with ₹50 review fee (bound) |
| **Theoretical Oracle Ceiling** | 97.2% | 0.0% | 57.5% | 2,065 | **₹109.00 lakh** | **₹23.30 lakh** | Unpenalized Bayes-optimal policy ceiling with hidden state access |

### Statistical Comparison & Break-Even Analysis

- **Bootstrap 95% Confidence Intervals (Resampling Disputes, N=1,000)**:
  - Automated-Only vs. Contest Everything ($p = 0$): Difference is **-₹67.85 lakh** with 95% CI **[-₹70.83 lakh, -₹64.37 lakh]**.
  - Automated-Only vs. Contest Everything ($p = ₹4,150$): Difference is **+₹10.12 lakh** with 95% CI **[+₹4.80 lakh, +₹15.53 lakh]**.
  - Scenario b vs. Contest Everything ($p = 0$): Difference is **-₹1.82 lakh** with 95% CI **[-₹1.86 lakh, -₹1.79 lakh]**.
  - Scenario b vs. Contest Everything ($p = ₹4,150$): Difference is **-₹1.32 lakh** with 95% CI **[-₹1.59 lakh, -₹1.01 lakh]**.
- **Symmetric Break-Even Loss Penalty Level**:
  - Live Policy (Automated-Only) flips above Contest Everything when the penalty exceeds **₹3,611.18**.
  - Scenario b flips above Contest Everything when the penalty exceeds **₹15,189.39**.
- **Empirical Snapshot**:
  - Auto-Contest Decisions: 1,324
  - Precision: 77.6% [75.3%, 79.8%]
  - Net Recovery: ₹26.58 Lakh [₹24.96 Lakh, ₹28.21 Lakh]

---

## Known Limitations and What This Is Not

- **What this is not**: Not an automated gateway payment executor (creates structured contest drafts, does not auto-submit externally); not a payment processor or acquirer; not legal or compliance advice.
- **Synthetic Circularity**: The bundled dataset is synthetic; models learn distributions embedded in the data generator. Real validation requires processor outcome logs.
- **Storage & Rate Limiting**: The SQLite WAL audit log is optimized for single-host deployments (~50-100 writes/sec); rate limiting is local in-memory per process.
- **Fail-Closed Guarantees**: Any malformed, missing, unverified, or ambiguous input routes to `HUMAN-REVIEW`, never `AUTO-CONTEST`.

---

## Documentation Links

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System boundaries, data flow, and threat model integration
- [docs/EVALUATION.md](docs/EVALUATION.md) — Full benchmark methodology, ablations, robustness tests, and BYOD harness
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — Deployment and operations notes, backups, anchoring, and measured load tests
- [docs/MODEL_CARD.md](docs/MODEL_CARD.md) — ML model characteristics, features, training data, and offline challengers
- [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) — Schema reference for dispute inputs, evidence items, and decisions
- [docs/DECISIONS.md](docs/DECISIONS.md) — Architecture decision records (ADRs)
- [SECURITY.md](SECURITY.md) — Security policy, vulnerability reporting, and hardening checklist
