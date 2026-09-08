# Security Notes

## Decision boundary

- The ML model is advisory.
- The graph is advisory.
- Economics is advisory.
- Deterministic policy is the only component that selects a final action.
- The Razorpay adapter produces a draft and has no live submission path in the demo or benchmark.

## Input handling

- Dispute IDs are constrained to a safe identifier pattern at the API boundary.
- Unknown reason codes are rejected.
- Amounts, model scores and graph scores are checked for finite valid ranges before policy evaluation.
- Evidence values are explicit booleans or unknown values; unknown is not treated as a positive result.
- Extra text fields are not interpreted as instructions by the decision engine.

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

## Model artifacts

Model files are trusted local artifacts loaded with Python pickle. They must not be replaced with untrusted files. The live scorer records model version, feature version, and scikit-learn version and rejects incompatible metadata when present.

## Secrets and credentials

Do not commit Razorpay credentials, API keys, tokens, or private keys. The repository's test/demo adapter does not require them.

## Deployment scope

Synthetic benchmark results are not production performance claims. SQLite is suitable for this local/demo repository but is not presented as a distributed production data store.
