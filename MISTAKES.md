# Mistakes and Fixes

This file records defects and design mistakes that were actually found while validating the repository. The entries are based on code inspection, tests, or executable checks.

## 1. `UNKNOWN` evidence could be too easily treated as usable evidence

**Problem.** Missing evidence needs to remain uncertainty rather than becoming an implicit positive result.

**Fix.** The canonical evidence engine keeps missing values as `WARN`, and the policy requires sufficient confirmed evidence before `AUTO-CONTEST`.

**Verified.** Safety regression tests cover missing and unknown evidence.

## 2. Model selection could inspect the final test split

**Problem.** The evaluation command recorded the model-selection basis using metrics calculated on `test.csv`, which violates a clean train/dev/test boundary.

**Fix.** Model selection now runs on `dev.csv` only. The test split is evaluated after the live model is frozen.

**Verified.** The training evaluator reports a separate development selection section and a final test section; regression tests cover the training evaluator.

## 3. A true evidence majority was not enforced at exactly 50%

**Problem.** The old comparison allowed 50% PASS evidence through because the boundary check used `< 0.5`.

**Fix.** The policy now requires a strict majority and rejects `pass_fraction <= 0.5` for automatic contesting.

**Verified.** A regression test covers the exact boundary.

## 4. High risk with missing evidence could bypass the evidence gate

**Problem.** A high model score should not be enough when the evidence packet was absent.

**Fix.** The policy now requires both a canonical evidence packet and evidence-quality result before `AUTO-CONTEST` can be considered.

**Verified.** Policy and safety regression tests cover high-confidence weak-evidence cases.

## 5. Counterfactual replay could analyze mutated input instead of the persisted case

**Problem.** A duplicate `dispute_id` can arrive with changed fields. Counterfactual analysis should describe the stored decision, not accidentally analyze the mutated retry payload.

**Fix.** Replay handling reconstructs the original dispute from the audit record before counterfactual analysis.

**Verified.** Replay and counterfactual tests now use the persisted case state.

## 6. A custom model artifact path was ignored by the scorer writer

**Problem.** The scorer's save helper accepted a path but the downstream training path could still write to the default artifact location.

**Fix.** Training passes the explicit output source to `save_ml_scorer`, and the helper writes to the supplied path.

**Verified.** The ML scorer tests cover custom-path behavior.

## 7. A proposed live-model recalibration did not improve held-out calibration

**Problem.** A local validation attempt replaced the existing calibration reference with a dev-fitted curve for the live model, but the untouched test calibration error worsened from 0.0237 to 0.0716.

**Fix.** The change was reverted under the stop rule. The existing calibration remains informational and does not participate in policy decisions.

**Verified.** The full regression suite passes with the reverted calibration path.

## 8. The temporal evaluator used incorrect dataset paths

**Problem.** The rewritten chronological check attempted to read `data/train`, `data/dev`, and `data/test` rather than their CSV files.

**Fix.** The evaluator now reads `train.csv`, `dev.csv`, and `test.csv` explicitly.

**Verified.** The temporal gate is rerun as part of final validation.

## 9. Evaluation latency was measured too narrowly

**Problem.** The old benchmark timed a tiny function rather than the actual end-to-end decision path.

**Fix.** `scripts/latency.py` warms the model and measures repeated calls through `decide_case(...)` with a temporary audit database.

**Verified.** The reported metric is explicitly named `LOCAL END-TO-END DECISION LATENCY`.

## 10. The repository had two Streamlit experiences for the same product story

**Problem.** Two dashboard files made the public/demo experience harder to explain.

**Fix.** The older dashboard was removed after reference analysis; `apps/app_deployed.py` is the single primary Streamlit experience, and the Makefile points to it.

**Verified.** UI tests and the full suite pass.
