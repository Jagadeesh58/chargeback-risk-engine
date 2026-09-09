# Chargeback Risk Engine

**Track 02 — AI Risk Manager**  
**Goal:** make chargeback decisions that maximize merchant value without letting an AI model bypass financial controls.

**Live demo:** https://chargebackriskengine.streamlit.app/

## The one-line pitch

> **AI proposes the risk. Evidence and economics explain the case. Deterministic policy decides what money-moving action is allowed.**

This is deliberately **not** just a chargeback classifier. The engine routes each dispute to:

- **AUTO-CONTEST** when risk, evidence, economics and safety gates all pass
- **HUMAN-REVIEW** when information is incomplete, contradictory, risky, uneconomic, or outside policy
- **ACCEPT-LOSS** when intervention is not economically justified

## Why the system is different

`Risk model → evidence quality → relationship context → expected value → bounded AI analyst → deterministic policy → immutable audit`

The AI analyst is advisory only. It may summarize evidence, identify missing/contradictory items, and draft an argument. It cannot change thresholds, bypass policy, or submit a chargeback.

## Current held-out evidence

The bundled dataset contains **20,000 train / 5,000 dev / 5,000 held-out test** cases. The evaluation data is synthetic and is not a production-performance claim.

The current held-out snapshot reports:

| Measure | Result |
|---|---:|
| PR-AUC | **0.719** |
| Auto-contest precision | **72.1%** |
| Auto-contest recall | **54.7%** |
| Realized net value | **₹60.83 lakh-equivalent synthetic units** |
| Lift vs dev-optimized Logistic-only | **+₹7.48 lakh-equivalent synthetic units** |
| P95 pure local routing latency | **~0.99 ms** |
| Frozen hard cases | **8 / 8 passed** |
| Release verification | **3 / 3 decisions + audit chain passed** |
| Regression suite | **166 tests passed** |

The important claim is not that a synthetic classifier has a spectacular headline metric. The stronger supported claim is that **the full decision system beats the dev-optimized model-only baseline on this frozen synthetic test set while preserving deterministic safety controls**. The repository does not claim production performance or a guaranteed hackathon rank.

## What was upgraded for judgeability

### 1. Honest ablation

`generate_report.py` now evaluates separate pipelines rather than relabeling the same pipeline as different ablations:

`Rules → Model → Evidence → Economics → Graph → Full`

The report explicitly notes when a capability cannot be measured by the tabular benchmark instead of inventing a lift.

### 2. Realized vs expected economics

The benchmark reports both modeled expected recovery and realized synthetic recovery, so the two are never conflated.

### 3. Development-only policy tuning

`chargeback_risk_engine/policy_optimizer.py` jointly tunes the routing threshold and evidence-confidence weight on `dev.csv`. The final test set is kept out of threshold selection, and the resulting `artifacts/policy_profile.json` is consumed by the live decision path.

### 4. Hard-case suite

`scripts/evaluate_hard_cases.py` covers missing evidence, contradictory evidence, high-value ceilings, replay/idempotency, prompt-injection text, graph escalation, malformed amounts, and a fully-confirmed positive.

### 5. Per-reason evaluation and uncertainty

The proof report includes per-reason PR-AUC/precision/recall and a bootstrap interval over case-level realized net value.

## Run it locally

```bash
make verify
streamlit run apps/app_deployed.py
uvicorn apps.api:app --reload
```

`make verify` runs the regression suite, dev-only policy optimization, held-out benchmark, hard-case suite, independent release verification, and proof-report generation. For an external public dataset, use `scripts/external_benchmark.py`; it is intentionally separate from the bundled headline benchmark.

## Judge path

Start at `docs/JUDGE_GUIDE.md` for a 90-second walkthrough, evidence map, and judge questions.

The proof bundle is written to `artifacts/`:

- `candidate_benchmark.json`
- `hard_cases_report.json`
- `policy_profile.json`
- `verification_report.json`
- `verification_report.html`
- model/calibration artifacts

## Safety contract

The policy engine remains the final authority. In particular:

- unknown evidence never silently becomes positive evidence
- contradictory evidence forces human review
- monetary ceilings cannot be bypassed by model confidence or caller input
- duplicate dispute IDs replay the original durable decision
- external AI failure falls back deterministically
- case notes are treated as untrusted data
- no external chargeback submission is executed by this repository

## Limitations

The bundled data is synthetic. The graph layer therefore cannot honestly claim a performance lift from the tabular test set because that dataset contains no historical relationship identifiers. Graph behavior is instead exercised in the frozen hard-case suite.

The current operating point deliberately trades recall for precision and safety. Human review is a feature, not a failure: the system is designed to abstain whenever evidence or economics is insufficient.

### Robustness and release proof

`make stress` runs a 1,000-row-per-case stress suite over the frozen held-out test set: extra evidence missingness, contradiction injection, shifted transaction amounts, and a deterministic drift report. These are explicitly robustness transformations, not external-data claims. See `docs/COMPETITION_UPGRADE.md` and `docs/FIVE_MINUTE_PITCH.md`.
