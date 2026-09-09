# Final Verification

## Required checks

`pytest -q` — **159 passed**

`python scripts/verify_no_leakage.py` — **passed**

`python scripts/benchmark.py` — **passed on 5,000 held-out rows**

`python scripts/latency.py` — p50 **2.119985 ms**, p95 **2.438868 ms**, p99 **2.968378 ms**

Focused adversarial and safety suite — **27/27 passed**

## Current candidate metrics

- Auto-contest precision: **0.7593833780160858**
- Auto-contest recall: **0.4012039660056657**
- Human-review rate: **0.637**
- Expected net value: **₹4,607,324.763838673**
- Logistic PR-AUC: **0.7234116688966661**
- Logistic calibration error: **0.007541071429129429**

## Evaluation data

Train: **20,000** rows

Dev: **5,000** rows

Held-out test: **5,000** rows

## Demo

The CLI demo runs five deterministic cases successfully: AUTO-CONTEST, HUMAN-REVIEW, graph escalation, weak evidence, and an economic boundary case.

## Deployment

Live demo: https://chargebackriskengine.streamlit.app/

The project includes the live demo URL supplied for the deployed Streamlit application. Automated access from this environment redirected to Streamlit authentication, so browser-level execution could not be independently verified here.
