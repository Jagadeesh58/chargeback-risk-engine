# Security Policy & Architecture

## 1. Responsible Disclosure Policy

The `chargeback-risk-engine` project values the contributions of the security research community. If you discover a vulnerability or potential security risk, please report it privately and responsibly so we can resolve the issue before public disclosure.

### Reporting a Vulnerability

- **Preferred Reporting Path**: Use GitHub Private Vulnerability Reporting on this repository.
- **Security Contact**: Email `security@example.com` with the subject line `[SECURITY] chargeback-risk-engine Vulnerability Report`.
- **GPG Key**: Available upon request or via public keyservers.

Please include the following information in your report:
1. Detailed description of the vulnerability, including affected endpoints or modules.
2. Step-by-step reproduction instructions or a minimal proof-of-concept script.
3. Potential impact assessment (e.g., authorization bypass, integrity failure, denial of service).
4. Any potential mitigations or remediations identified.

### Response Timelines & SLAs

- **Initial Acknowledgment**: Within 48 hours of report receipt.
- **Triage & Severity Assessment**: Within 5 business days.
- **Fix & Patch Deployment**: Targeted within 14 business days for critical vulnerabilities.
- **Public Disclosure**: Coordinated disclosure after release of fix or 90 days following initial report, whichever occurs first.

---

## 2. Core Decision Boundary

- **Machine Learning is Advisory**: The ML win probability score is strictly an advisory signal.
- **Graph Clustering is Advisory**: Risk graph entity clustering produces risk scores that may escalate disputes to review, but cannot approve an automated contest.
- **Economics is Advisory**: Expected net value calculations are advisory filters; high EV cannot bypass safety or evidence gates.
- **AI Analyst is Advisory**: External LLM case analyses produce notes and counterfactuals but cannot alter decision outcomes.
- **Deterministic Policy is Sole Authority**: Only `chargeback_risk_engine.policy.decide()` can select a final financial action (`AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS`).
- **Payment Gateway Adapter**: Produces representment packet drafts; no direct money movements are executed in demo, evaluation, or benchmark modes.

---

## 3. Input Handling, Rate Limiting, and Size Boundaries

- **Dispute Identifiers**: Dispute IDs are constrained to a safe alphanumeric pattern at the API boundary (`^[A-Za-z0-9_-]{1,64}$`).
- **Reason Codes**: Only recognized card-brand reason codes are accepted; unknown reason codes are rejected with HTTP 422.
- **Payload Size Caps**: Request bodies are capped by default at 64 KB (configurable via `CHARGEBACK_MAX_BODY_BYTES`), rejecting oversized payloads with HTTP 413. For chunked transfer-encoding, payloads are streamed and aborted immediately upon exceeding the threshold without buffering full inputs into memory.
- **Rate Limiting**: Evaluated prior to reading or buffering request bodies, protecting server memory from unauthenticated payload floods (`CHARGEBACK_RATE_LIMIT_RPS`). In-memory tracking uses an LRU-evicted client cache (`_MAX_CLIENT_ENTRIES = 5000`).
- **Reverse-Proxy Client IP Boundary**: The in-memory rate limiter inspects direct socket connection (`request.client.host`). In production deployments behind a CDN, API gateway, or reverse proxy (e.g., Cloudflare, AWS ALB, NGINX), `request.client.host` reflects the internal reverse proxy IP unless trusted proxy middleware parses upstream headers. Edge rate limiting (e.g. Redis Token Bucket or Envoy filter) is recommended for distributed multi-instance clusters.
- **Score and Amount Boundaries**: Amounts, model scores, and graph scores are validated for finite numeric ranges before policy evaluation.
- **Evidence Verification**: Evidence values must be explicit booleans or missing; unverified or missing evidence is never treated as a positive result.

---

## 4. Authentication, Roles, and Key Rotation

- **Authentication Modes**:
  - In local development or demo environments where `CHARGEBACK_API_KEY` is unset, the engine runs in demo mode (`auth: "demo-open"` on `/health`), logging a visible warning on startup.
  - When configured, `/decision`, `/score`, `/audit/verify`, and `/metrics` enforce the `X-API-Key` header with constant-time comparison (`hmac.compare_digest`).
- **Multi-Key Configuration & Rotation**:
  - `CHARGEBACK_API_KEYS` supports multiple active credentials formatted as `key_id:secret:role[,key_id:secret:role,...]`.
  - Zero-downtime key rotation is achieved by deploying both old and new keys simultaneously during transition windows.
- **Role-Based Access Control**:
  - `read`: Can inspect health and calculate advisory scores (`/score`).
  - `write`: Can submit disputes for policy decision (`/decision`).
  - `admin`: Can execute integrity verifications (`/audit/verify`), export signed head anchors (`/audit/head/anchor`), and scrape telemetry (`/metrics`).

---

## 5. Safety Invariants Under Test

The automated regression suite verifies that:
1. Monetary ceilings (`₹50,000`) cannot be bypassed by high model confidence.
2. Missing evidence cannot become sufficient because the model win probability is high.
3. `UNKNOWN` or unverified evidence does not become `PASS`.
4. Contradictory or invalid evidence cannot silently become safe evidence.
5. Graph risk escalation can force `HUMAN-REVIEW`.
6. Economics cannot override safety gates; policy does not trust caller-supplied expected value.
7. Duplicate requests replay the original stored decision.
8. Malformed or out-of-bounds input cannot force `AUTO-CONTEST`.
9. Model output does not directly execute a financial action.

---

## 6. Model Artifacts & Integrity Verification

- **Elimination of Pickle**: Serialized Python pickle files (`.pkl`) are strictly prohibited in production runtimes due to arbitrary code execution risks.
- **Transparent JSON Weights**: Model parameters (feature coefficients, intercept, scaling factors) are stored as human-readable JSON files (`ml_scorer_model.json`).
- **Cryptographic Digest Sidecars**: Model files are accompanied by a `.sha256` digest sidecar. The SHA-256 checksum is strictly validated at server startup (`CHARGEBACK_REQUIRE_MODEL_HASH=1`).
- **Metadata Compatibility**: Scorer initialization verifies model version, feature version, and runtime schema compatibility.

---

## 7. Audit Hash Chain Boundaries & Concurrency

- **SHA-256 Hash Chaining**: Every decision record links to the previous entry's SHA-256 digest (`record_hash = SHA256(prev_hash + canonical_json)`).
- **Concurrency & WAL Mode**: SQLite runs in Write-Ahead Logging mode (`PRAGMA journal_mode = WAL`) with busy timeouts (`PRAGMA busy_timeout = 5000`) and serialized in-process mutexes (`_AUDIT_WRITE_LOCK`) to prevent chain forking under concurrent writes.
- **External Head Anchoring**: To protect against complete tail deletion by an adversary with database filesystem access, the current head hash can be exported via `GET /audit/head/anchor`. This emits an HMAC-SHA256 signature signed with `CHARGEBACK_ANCHOR_SECRET`, suitable for publishing to an append-only transparency log or write-once ledger.

---

## 8. PII Storage & Data Privacy (GDPR & Indian DPDP Act 2023)

The persistent audit database stores:
- **Identifiers**: `dispute_id`, `payment_id`, `customer_id`, `device_id`, `ip_address`, `card_fingerprint`.
- **Decision Context**: Dispute amount, reason code, evidence checklist items, win probability, and financial action.

### Privacy Remediation Recommendations:
1. **Pseudonymization**: Buyer identifiers (`customer_id`, `ip_address`, `card_fingerprint`) should be hashed using a keyed HMAC before persistence.
2. **Crypto-Shredding**: For statutory Right to Erasure requests (GDPR Art. 17 / Indian DPDP Act 2023), store sensitive fields encrypted with a per-customer encryption key. Deleting the customer key makes historical PII unrecoverable without breaking cryptographic audit chain linkage.
3. **Data Retention**: Partition and archive audit logs after applicable card-brand representment windows expire (typically 180 to 540 days).

---

## 9. Privacy & Third-Party AI Egress

When `CHARGEBACK_AI_ANALYST_URL` is configured, dispute notes and evidence details are sent via HTTP POST to the external analysis service. Deployments processing production cardholder data or sensitive PII must ensure the target URL is an internal, authorized service compliant with data governance policies, or redact sensitive customer details before forwarding.

---

## 10. Secrets & Credentials Management

Do not commit API keys, secrets, or certificates to source control. The repository relies entirely on environment variable configuration (`CHARGEBACK_API_KEYS`, `CHARGEBACK_ANCHOR_SECRET`). Production deployments should inject secrets from a dedicated secrets manager (e.g. HashiCorp Vault, AWS Secrets Manager, or Kubernetes Secrets).
