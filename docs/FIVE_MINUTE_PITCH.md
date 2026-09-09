# Five-minute judge pitch

## 0:00–0:40 — The problem
Chargeback automation has two failure modes: losing money by accepting a contest that cannot be supported, or losing recoverable money by being too conservative. The product therefore optimizes **recoverable net value**, not raw model accuracy.

## 0:40–1:30 — Architecture
`Model probability -> evidence provenance/quality -> economic value -> relationship risk -> deterministic policy -> audit receipt`

The AI analyst is advisory only. It cannot submit a chargeback, change thresholds, bypass the monetary ceiling, or override a deterministic safety gate.

## 1:30–2:30 — Why it is different
The benchmark compares the **same frozen Logistic model** two ways:

1. model-only thresholding;
2. the complete evidence/economic/risk/policy system.

The policy is selected on `dev.csv`; `test.csv` remains untouched until final evaluation.

## 2:30–3:20 — Results
Show `artifacts/candidate_benchmark.json` and the proof report. The current bundled benchmark reports:

- PR-AUC: 0.7192
- auto-contest precision: 72.10%
- auto-contest recall: 54.71%
- realized net value: ₹60.83 lakh-equivalent synthetic units
- +₹7.48 lakh / +14.0% realized-net lift vs the dev-optimized model-only baseline

Immediately disclose that the bundled dataset is synthetic.

## 3:20–4:10 — Safety proof
Run:

```bash
python scripts/verify_release.py
python scripts/evaluate_hard_cases.py
```

Point out the high-value controls: invalid evidence, contradiction routing, replay/idempotency, graph escalation, monetary ceiling, prompt-injection resistance, and tamper-evident audit verification.

## 4:10–4:40 — Robustness
Run:

```bash
make stress
```

The stress benchmark deliberately labels itself as a transformation of the frozen test set rather than an external-data claim. It tests extra missingness, contradictions, amount shift, and deterministic drift diagnosis.

## 4:40–5:00 — Close
The thesis is simple: **AI can recommend, but a financial system needs deterministic authority, measurable economics, and proof that the decision can be audited and replayed.**
