# Threat Model

| Threat | Control |
|---|---|
| prompt injection in case notes | notes are untrusted; AI analyst cannot change policy |
| caller-supplied expected value | policy recalculates canonical economics |
| amount manipulation | input validation + monetary ceiling |
| contradictory evidence | deterministic evidence gate → HUMAN-REVIEW |
| missing evidence | WARN state + completeness gate |
| duplicate request | durable idempotency keyed by dispute ID |
| replay | original durable decision is returned |
| AI outage | deterministic local fallback |
| graph abuse | network signal can only escalate to review |
| retry abuse | contest-count limit |
| model error | model is advisory; deterministic policy remains authoritative |
