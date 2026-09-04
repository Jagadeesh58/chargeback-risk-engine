# Evaluation Report

## Scope
All reported numbers are generated from the repository's synthetic dataset and scripts. No production Razorpay traffic or credentials are used.

## Evaluation commands

```bash
python scripts/generate_data.py --out-dir data
python training/train_models.py
python training/evaluate_temporal.py
python -m chargeback_risk_engine.calibration
pytest -q
python scripts/demo.py
python scripts/benchmark.py
```

## Model comparison
`training/train_models.py` reports the rules baseline, Logistic Regression, Histogram Gradient Boosting, and the transparent hybrid probability recommendation using the fixed weights in `config.py`. The hybrid probability is advisory; evidence, economics, graph escalation, and deterministic policy are applied afterward.

## Safety evaluation
The suite verifies the following invariant: a high model probability cannot bypass the monetary ceiling, insufficient/invalid/contradictory evidence, graph-risk escalation, contest limits, or external-service fallback. Duplicate dispute IDs replay the original persisted decision.

## Calibration
`calibration.py` fits isotonic calibration on `dev.csv` and measures it separately on `test.csv`. Calibration is informational and is not silently substituted into policy thresholds.

## Limitations
- The dataset is synthetic.
- The relationship graph is rebuilt from relationship identifiers stored in local SQLite; it is not a distributed graph store.
- The feedback store is local SQLite.
- Razorpay connectivity is not claimed as live.
- Hybrid weights are explicit engineering choices, not statistically optimized on the held-out test set.
