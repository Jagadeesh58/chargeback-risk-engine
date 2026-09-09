# Competition upgrade: what is actually novel

This release focuses on measurable engineering rather than cosmetic AI features.

## 1. Model vs system proof

The held-out benchmark freezes the model after train/dev selection and compares a pure model-only threshold against the same model behind deterministic evidence and economic gates. The test set is never used to choose the policy.

## 2. Robustness suite

`make stress` evaluates controlled transformations of the frozen test set:

- 25% extra evidence missingness
- 20% contradiction injection
- shifted transaction amounts
- deterministic drift diagnosis

These are explicitly labeled as **stress transformations**, not external-data results.

## 3. Drift-safe adaptation

`chargeback_risk_engine/monitoring/drift_guard.py` detects distribution shift and recommends recalibration/human review. It cannot retrain or promote the model. This follows the core financial-control principle: probabilistic diagnosis may suggest adaptation, but deterministic governance remains authoritative.

## 4. Independent verification

`make verify` remains the primary judge command. It checks regression tests, dev-only optimization, held-out evaluation, hard cases, policy/audit integrity, and report generation.

## 5. Track positioning

The repository is still **Track 02 first**. The optional Track 01/03/04 primitives demonstrate reusable safety patterns but are not presented as a claim that one submission satisfies all tracks simultaneously.
