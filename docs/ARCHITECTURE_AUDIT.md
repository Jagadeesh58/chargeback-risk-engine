# Architecture Audit

The repository uses one authoritative decision service shared by the API, dashboard, demo, and evaluation code.

The core path is:

`Input → Risk score → Evidence verification → Relationship graph → Economic value → Bounded evidence analyst → Deterministic policy → Audit`

The live risk estimator is a single reason-aware Logistic Regression model. Rules, HGB, and other scoring variants are evaluation challengers rather than alternate live decision paths.

The relationship graph is deliberately small. It links privacy-safe historical identifiers such as customer, device, IP, payment fingerprint, and merchant references and produces a cluster/ring risk signal without creating a separate graph service.

The evidence analyst validates structured output and falls back to deterministic analysis when an external endpoint is unavailable or malformed. The analyst cannot select the final action.

The audit store is SQLite with idempotent inserts and a SHA-256 hash chain. The stored record includes the decision, versions, evidence, graph inputs, AI metadata, request ID, timestamp, and integrity hashes.

The application remains monolithic by design. No queue, service mesh, graph database, mandatory LLM dependency, or unnecessary cloud integration is required to run the decision path locally.
