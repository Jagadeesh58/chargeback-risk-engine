# Competitive gap closure

This release deliberately implements the strongest reusable engineering patterns visible in public Razorpay Buildathon repositories without copying their code.

## What was added

### Evidence-weighted routing
The calibrated model probability remains separate from the final routing score. Evidence provenance is treated as an explicit signal and is tuned only on `dev.csv`.

### Economic optimization
Threshold selection is constrained by a minimum automation precision and maximum automation rate, with expected and realized net value reported independently.

### Capacity awareness
The proof bundle includes a review-budget frontier so judges can inspect how the system behaves when analyst capacity is scarce.

### Independent verification
`independent_verifier.py` checks the released decision object without invoking the LLM or orchestrator. Release verification also checks the tamper-evident SQLite audit chain.

### Hard-case safety regression
The frozen suite covers missing evidence, contradictions, monetary ceilings, replay/idempotency, prompt-injection text, graph escalation, malformed amounts, and a positive reference case.

### External-data adapter
`scripts/external_benchmark.py` evaluates a separately supplied held-out CSV with the same policy boundary. It does not contaminate the bundled benchmark.

## Important honesty boundary

The bundled benchmark remains synthetic. The release does **not** claim production predictive performance or a win guarantee. The strongest claim supported by the repository is that the full system is reproducible, safety-bounded, evidence-aware, and measurably better than its dev-optimized model-only baseline on the bundled held-out benchmark.
