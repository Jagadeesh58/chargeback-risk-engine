# Final Verification

## Verification contract

This document records the repository verification contract. The authoritative test count is the result of the current local or CI run; it is intentionally not hard-coded here so the document does not become stale when tests change.

Run the full verification workflow with:

```bash
make verify
```

`make verify` consumes the tracked `artifacts/policy_profile.json` as the frozen
release policy. Use `make policy-optimize` separately when deliberately selecting
a new development policy from `dev.csv`, then review and commit the resulting profile.

The workflow covers:

1. the complete pytest suite
2. leakage verification
3. held-out benchmark generation using the frozen tracked policy profile
4. deterministic hard-case verification
5. release safety verification
6. reproducible evaluation-report generation

Additional checks are available through:

```bash
python scripts/verify_no_leakage.py
python scripts/latency.py
```

## Evaluation data

| Split | Rows |
|---|---:|
| Train | 20,000 |
| Development | 5,000 |
| Held-out test | 5,000 |

The bundled dataset is synthetic. It is included for reproducible development and evaluation and is not a representation of production Razorpay traffic.

## Safety verification

The verification suite covers policy boundaries, malformed and missing evidence, contradictory evidence, duplicate/replay behavior, monetary ceilings, prompt-injection-style case text, graph escalation, AI fallback behavior, counterfactual isolation, and audit integrity.

## Latency

Run `python scripts/latency.py` to obtain the current local timing snapshot. The benchmark is a warm single-process measurement and is not a production SLA.

## Release notes

Generated benchmark and verification artifacts are intentionally treated as reproducible outputs. Only small, reviewable artifacts are kept in Git.
