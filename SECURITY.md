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
- Request body size is capped by default at 64 KB (configurable via `CHARGEBACK_MAX_BODY_BYTES`), rejecting larger payloads with 413.
- In-memory per-client rate limiting is available via `CHARGEBACK_RATE_LIMIT`, returning 429 with `Retry-After`. Rate limits are keyed strictly on remote network IP (`request.client.host`) to prevent spoofing bypasses.
- Amounts, model scores and graph scores are checked for finite valid ranges before policy evaluation.
- Evidence values are explicit booleans or unknown values; unknown is not treated as a positive result.
- Extra text fields are not interpreted as instructions by the decision engine.

## Authentication and API access

- API authentication is optional for local development/demo: when `CHARGEBACK_API_KEY` is unset, the engine runs in demo mode (`auth: "demo-open"` on `/health`).
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

Pickle deserialization executes arbitrary code and is only safe for trusted, hash-verified files. Model artifacts are accompanied by a `.sha256` sidecar file containing their SHA-256 digest. When loading `ml_scorer_model.pkl`, the SHA-256 checksum is verified before unpickling; mismatches raise a ValueError. Setting `CHARGEBACK_REQUIRE_MODEL_HASH=1` strictly requires the sidecar file. The live scorer additionally records model version, feature version, and scikit-learn version and rejects incompatible metadata.

## Audit hash chain boundaries & concurrency

The SQLite audit log links decisions into a SHA-256 hash chain. Writes are serialized via thread locks and database-level `BEGIN IMMEDIATE` transactions to prevent chain forking under concurrency.
- **Tamper Evidence Boundary**: The hash chain provides tamper-evidence against partial edits, in-place record mutations, and retroactive modifications.
- **Threat Boundary**: An adversary with unrestricted filesystem or SQLite database write access could recompute the entire hash chain from scratch, and tail deletion is undetectable without external anchoring. Production systems should periodically publish the head digest to an external append-only log or write-once ledger.

## Privacy & third-party AI disclosure

When `CHARGEBACK_AI_ANALYST_URL` is configured, unstructured dispute notes (`evidence_text`), reason codes, and assembled evidence lists are transmitted via HTTP POST to the external service. Deployments processing production cardholder data or sensitive PII must ensure the target URL is an internal, authorized service compliant with data governance rules, or redact sensitive customer details before forwarding.

## Secrets and credentials

Do not commit credentials, API keys, tokens, or private keys. The repository's test/demo adapter does not require them.

## Deployment scope & limitations

- Synthetic benchmark results are not production performance claims.
- SQLite is suitable for this local/demo repository but is not presented as a distributed production data store.
- The in-memory rate limiter is per-process and intended for local daemon protection. Distributed deployments should enforce rate limits and DDoS mitigation at the edge/gateway layer.
