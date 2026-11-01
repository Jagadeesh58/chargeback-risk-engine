# STRIDE Threat Model

This document outlines the security architecture and threat landscape for `chargeback-risk-engine`, classified using the **STRIDE** methodology (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege). Every mitigation references the authoritative implementation source and its verification test.

---

## 1. System Overview & Trust Boundaries

The chargeback risk engine processes financial dispute data from upstream merchant order systems and payment gateway webhooks. It produces advisory machine learning and evidence quality signals, routes disputes through a deterministic financial policy layer, and logs immutable audit records.

```text
       [ External Clients / Webhooks ]
                     │  (HTTPS + API Key)
 ─── Trust Boundary 1: Ingress / Edge ────────────────────────
                     ▼
             [ FastAPI Gateway ]
         (CORS, Rate Limiter, Body Limit)
                     │
 ─── Trust Boundary 2: Core Engine ───────────────────────────
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
 [ ML Scorer ]  [ Evidence ]  [ Risk Graph ]
 (Advisory)     (Advisory)    (Advisory)
      │              │              │
      └──────────────┼──────────────┘
                     ▼
       [ Deterministic Policy Engine ]  <-- Sole Financial Authority
                     │
 ─── Trust Boundary 3: Persistence & Egress ──────────────────
      ┌──────────────┴──────────────┐
      ▼                             ▼
 [ SQLite Audit Trail ]    [ External AI Analyst ]
 (SHA-256 Hash Chaining)   (Untrusted / Advisory)
```

---

## 2. STRIDE Threat Analysis

### 2.1 Spoofing (S)

| Threat | Impact | Mitigations & Controls | Implementation File | Verification Test |
|---|---|---|---|---|
| **API Client Identity Spoofing** | High | Multi-key credential authentication (`CHARGEBACK_API_KEYS`) with key rotation (`key_id:secret:role`). Constant-time comparison (`hmac.compare_digest`) prevents timing attacks. Production startup rejects missing/empty keys. | `chargeback_risk_engine/api.py` | `tests/test_api_production.py` |
| **Client IP Spoofing behind Proxies** | Medium | In-memory rate limiting inspects direct client connection (`request.client.host`). Production guidance explicitly documents edge proxy configuration. | `chargeback_risk_engine/api.py` | `tests/test_api_production.py` |
| **Model Weights Spoofing** | Critical | Arbitrary pickle deserialization is eliminated. Model weights are stored in transparent JSON format. SHA-256 checksum sidecars (`.sha256`) are verified during startup. | `chargeback_risk_engine/ml_scorer.py` | `tests/test_model_artifact_safety.py` |

---

### 2.2 Tampering (T)

| Threat | Impact | Mitigations & Controls | Implementation File | Verification Test |
|---|---|---|---|---|
| **Input Payload Manipulation** | High | Strict Pydantic input models enforce schema validation and reject unexpected fields. Monetary ceiling (`MONETARY_CEILING = ₹50,000`) and range checks (`0.0 <= amount <= ₹1,000,000`) prevent runaway automation. | `chargeback_risk_engine/policy.py` | `tests/test_policy_boundaries.py` |
| **Prompt Injection in Case Notes** | Medium | Dispute notes are treated as unparsed passive data strings. The external AI analyst is strictly advisory and cannot alter deterministic policy rules or execute financial actions. | `chargeback_risk_engine/ai_analyst.py` | `tests/test_adversarial_suite.py` |
| **Historical Audit Log Modification** | Critical | Append-only SQLite tables with cumulative SHA-256 hash chaining (`record_hash = SHA256(prev_hash + record)`). Any retroactive record edit or row deletion invalidates subsequent chain linkage. | `chargeback_risk_engine/audit_log.py` | `tests/test_audit_log.py` |
| **Contradictory or Malformed Evidence** | Medium | Deterministic evidence validator checks consistency; contradictory or unverified evidence forces `WARN` state and routes decision to `HUMAN-REVIEW`. | `chargeback_risk_engine/engine/evidence_score.py` | `tests/test_evidence_provenance.py` |

---

### 2.3 Repudiation (R)

| Threat | Impact | Mitigations & Controls | Implementation File | Verification Test |
|---|---|---|---|---|
| **Dispute Decision Repudiation** | High | Cryptographic audit logging with actor provenance (`actor`), ISO 8601 UTC timestamps, request IDs, and SHA-256 record hashes for every decision. | `chargeback_risk_engine/audit_log.py` | `tests/test_audit_store.py` |
| **Audit Head Truncation / Rollback** | Medium | External head anchoring (`/audit/head/anchor`) signs the current head hash and timestamp with an HMAC-SHA256 secret (`CHARGEBACK_ANCHOR_SECRET`). Anchors can be periodically pushed to an immutable ledger or WORM storage. | `scripts/export_audit_head.py` | `tests/test_export_audit_head.py` |
| **Idempotency Replay / Drift** | Medium | Exact request payload hash stored on initial write. Duplicate submissions replay original stored decision. Mutated payloads on an existing dispute ID raise `409 Conflict`. | `chargeback_risk_engine/api.py` | `tests/test_api_production.py` |

---

### 2.4 Information Disclosure (I)

| Threat | Impact | Mitigations & Controls | Implementation File | Verification Test |
|---|---|---|---|---|
| **PII Leakage in Audit Trail** | Medium | *Design notes, not legal advice*: Keyed HMAC pseudonymization and per-customer crypto-shredding (for GDPR Art. 17 / Indian DPDP Act 2023 compliance) are documented architectural design proposals; the current engine stores raw payloads. Production deployments must integrate pre-ingestion tokenization or field-level encryption. | Design Proposal (`docs/THREAT_MODEL.md`) | `tests/test_audit_store.py` |
| **Stack Trace & Internal Path Leakage** | Low | Global FastAPI exception handlers sanitize error responses into standardized JSON messages, withholding internal traces. Production settings suppress debug output. | `chargeback_risk_engine/api.py` | `tests/test_api_production.py` |
| **Third-Party AI Analyst Egress** | Medium | AI analyst is optional and disabled by default. When enabled, requests require explicit internal URL configuration (`CHARGEBACK_AI_ANALYST_URL`). | `chargeback_risk_engine/ai_analyst.py` | `tests/test_ai_analyst_evaluation.py` |

---

### 2.5 Denial of Service (DoS)

| Threat | Impact | Mitigations & Controls | Implementation File | Verification Test |
|---|---|---|---|---|
| **Payload Memory Exhaustion** | High | Streaming request body limit middleware enforces a strict 1 MB cap (`CHARGEBACK_MAX_BODY_BYTES`) before buffering into memory, returning HTTP 413 on overflow. | `chargeback_risk_engine/api.py` | `tests/test_api_production.py` |
| **Request Flooding / API Abuse** | Medium | In-memory token-bucket rate limiter evaluated prior to request body reading (`CHARGEBACK_RATE_LIMIT`). Memory-bounded client tracking with LRU eviction. | `chargeback_risk_engine/api.py` | `tests/test_api_production.py` |
| **SQLite Concurrency Contention** | Medium | SQLite configured with Write-Ahead Logging (`PRAGMA journal_mode = WAL`), `PRAGMA busy_timeout = 5000`, and serialized write locks (`_AUDIT_WRITE_LOCK`). | `chargeback_risk_engine/audit_log.py` | `tests/test_hardening_probes.py` |
| **External Service Latency / Hangs** | Medium | Strict HTTP request timeout (`CHARGEBACK_REQUEST_TIMEOUT_SECONDS = 5.0`) with deterministic local fallback if the external service fails or times out. | `chargeback_risk_engine/ai_analyst.py` | `tests/test_adversarial_suite.py` |

---

### 2.6 Elevation of Privilege (E)

| Threat | Impact | Mitigations & Controls | Implementation File | Verification Test |
|---|---|---|---|---|
| **Role Escalation via API Key** | High | Role-based authorization: API keys mapped to `read`, `write`, or `admin` scopes. Administrative routes (`/audit/verify`, `/metrics`) require privileged credentials. | `chargeback_risk_engine/api.py` | `tests/test_api_production.py` |
| **Model Component Authority Escalation** | Critical | **Core Architecture Invariant**: ML models, graph clustering algorithms, and LLM analysts are strictly advisory. Only the deterministic Python policy module (`chargeback_risk_engine.policy.decide`) selects financial actions (`AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS`). | `chargeback_risk_engine/policy.py` | `tests/test_safety_regression.py` |
| **Arbitrary Code Execution via Deserialization** | Critical | Pickle deserialization is completely eliminated and banned across the production runtime. Machine learning parameters are loaded strictly as primitive JSON weights. | `chargeback_risk_engine/ml_scorer.py` | `tests/test_model_artifact_safety.py` |

---

## 3. Security Boundary Summary

| Component | Classification | Permitted Actions | Prohibited Actions |
|---|---|---|---|
| **ML Risk Scorer** | Advisory | Output win probability score in [0.0, 1.0] | Selecting financial action, approving auto-contest |
| **Evidence Scorer** | Advisory | Output completeness score, missing flags | Overriding monetary ceiling, forcing auto-contest |
| **Risk Graph** | Advisory | Output network clustering risk score | Downgrading review to auto-contest |
| **AI Case Analyst** | Advisory | Suggest counterfactual explanations, summary notes | Mutating decision state, executing money movements |
| **Policy Engine** | **Authoritative** | Select `AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS` | Blindly trusting unverified inputs |
