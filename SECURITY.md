# Security Notes

## Decision boundary

- The ML model is advisory.
- The graph is advisory.
- Economics is advisory.
- Deterministic policy is the only component that selects a final action.
- The payment-gateway adapter produces a draft and has no live submission path in the demo or benchmark.

## Input handling, rate limiting, and size boundaries

- Dispute IDs are constrained to a safe identifier pattern at the API boundary.
- Unknown reason codes are rejected.
- Request body size is capped by default at 64 KB (configurable via `CHARGEBACK_MAX_BODY_BYTES`), rejecting larger payloads with 413. For chunked transfer-encoding, payloads are streamed and aborted immediately as soon as byte accumulation exceeds the threshold without buffering full inputs.
- Rate limiting is evaluated prior to reading or buffering request bodies, protecting server memory from unauthenticated payload floods. In-memory per-client tracking is memory-bounded with LRU eviction of expired clients (`_MAX_CLIENT_ENTRIES = 5000`).
- **Reverse-Proxy Client IP Boundary**: The in-memory rate limiter inspects `request.client.host`. In production environments operating behind a CDN, API gateway, or reverse proxy (e.g., Cloudflare, AWS ALB, NGINX), `request.client.host` reflects the internal reverse proxy IP unless trusted proxy middleware explicitly parses `X-Forwarded-For`. Blindly trusting `X-Forwarded-For` without upstream proxy validation exposes the service to IP spoofing and rate limit bypasses. In distributed production, rate limiting and DDoS mitigation should be offloaded to an edge gateway (e.g. Redis-backed Token Bucket or Envoy filter).
- Amounts, model scores and graph scores are checked for finite valid ranges before policy evaluation.
- Evidence values are explicit booleans or unknown values; unknown is not treated as a positive result.
- Extra text fields are not interpreted as instructions by the decision engine.

## Authentication and API access

- API authentication is optional for local development/demo: when `CHARGEBACK_API_KEY` is unset, the engine runs in demo mode (`auth: "demo-open"` on `/health`), logging a visible warning on startup.
- When `CHARGEBACK_API_KEY` is configured, `/decision`, `/score`, and `/audit/verify` enforce the `X-API-Key` header with constant-time comparison (`hmac.compare_digest`). `/health` remains accessible for liveness checks.

## Safety invariants under test

The regression suite verifies that:

- monetary ceilings cannot be bypassed by high model confidence
- missing evidence cannot become sufficient because the model score is high
- `UNKNOWN` evidence does not become `PASS`
- contradictory/invalid evidence cannot silently become safe evidence
- graph escalation can force `HUMAN-REVIEW`
- economics cannot override safety gates, and policy does not trust a caller-supplied expected value
- duplicate requests replay the stored decision
- malformed input cannot force `AUTO-CONTEST`
- model output does not directly execute a financial action

## Model artifacts & integrity verification

Pickle deserialization executes arbitrary code and is only safe for trusted, hash-verified files. Model artifacts are accompanied by a `.sha256` sidecar file containing their SHA-256 digest. When loading `ml_scorer_model.pkl`, the SHA-256 checksum is verified before unpickling; mismatches raise a ValueError.
- **Threat Model**: Loading pickled model weights is secure against external runtime attackers because the model file and sidecar are local filesystem artifacts. Tampering with the model requires either direct write access to the host repository/filesystem or compromise of the CI/CD artifact pipeline. Setting `CHARGEBACK_REQUIRE_MODEL_HASH=1` (or loading the committed production model) strictly enforces hash presence and rejects missing sidecars. For multi-tenant or untrusted model distribution, models should be exported as raw parameters (weights and biases in JSON) rather than serialized Python object graphs.
The live scorer additionally records model version, feature version, and scikit-learn version and rejects incompatible metadata.

## Audit hash chain boundaries & concurrency

The SQLite audit log links decisions into a SHA-256 hash chain. Writes are serialized via thread locks and database-level `BEGIN IMMEDIATE` transactions to prevent chain forking under concurrency.
- **Tamper Evidence Boundary**: The hash chain provides tamper-evidence against partial edits, in-place record mutations, and retroactive modifications.
- **Threat Boundary**: An adversary with unrestricted filesystem or SQLite database write access could recompute the entire hash chain from scratch, and tail deletion is undetectable without external anchoring. Production systems should periodically publish the head digest to an external append-only log or write-once ledger.

## PII storage and data retention (GDPR & Indian DPDP Act)

The persistent audit database (`audit_log.db`) records:
- **Identifiers**: `dispute_id`, `payment_id`, `customer_id`, `device_id`, `ip_address`, `card_fingerprint`.
- **Decision Context**: Dispute amount, reason code, evidence checklist items, win probability, and financial action.

**Regulatory Considerations (GDPR Article 17 / Indian DPDP Act 2023)**:
Data principals have statutory rights to request erasure of personal data. However, in an immutable cryptographic audit chain, mutating or deleting a historical record breaks the SHA-256 hash linkage for all subsequent records, making native row deletion incompatible with tamper-evident auditing.

**Architectural Remediation**:
1. **Identifier Pseudonymization**: In production, buyer identifiers (`customer_id`, `ip_address`, `card_fingerprint`) should be passed through a keyed HMAC or salted cryptographic hash before entering the audit log.
2. **Cryptographic Erasure (Crypto-Shredding)**: Sensitive fields can be encrypted with a per-customer key. To fulfill a "Right to Erasure" request, deleting the customer's encryption key renders the ciphertext permanently unrecoverable without modifying historical database rows or breaking audit chain integrity.
3. **Retention Windows**: Audit databases should be partitioned and pruned after the applicable card brand chargeback representment window (typically 180 to 540 days under card network operating rules).

## Privacy & third-party AI disclosure

When `CHARGEBACK_AI_ANALYST_URL` is configured, unstructured dispute notes (`evidence_text`), reason codes, and assembled evidence lists are transmitted via HTTP POST to the external service. Deployments processing production cardholder data or sensitive PII must ensure the target URL is an internal, authorized service compliant with data governance rules, or redact sensitive customer details before forwarding.

## Secrets and credentials

Do not commit credentials, API keys, tokens, or private keys. The repository's test/demo adapter does not require them.

## Deployment scope & limitations

- Synthetic benchmark results are not production performance claims.
- SQLite is suitable for this local/demo repository but is not presented as a distributed production data store.
- The in-memory rate limiter is per-process and intended for local daemon protection. Distributed deployments should enforce rate limits and DDoS mitigation at the edge/gateway layer.
