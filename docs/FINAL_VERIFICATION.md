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

The Streamlit app is ready for Streamlit Community Cloud, but a live public URL could not be created from this environment because no authenticated Streamlit Cloud/GitHub deployment connection is available. No placeholder or unverified URL is included in the project.
