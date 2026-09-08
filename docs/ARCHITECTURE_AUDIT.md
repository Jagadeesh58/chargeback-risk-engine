# Architecture Audit

## Audit outcome

The existing repository already had useful evidence, policy, economics, graph, audit, model, API, and test infrastructure. The upgrade therefore consolidates and simplifies rather than replacing the application.

The largest justified architectural change is the creation of a **single canonical decision path** and a bounded **counterfactual decision analysis** capability.

## Kept

- synthetic train/dev/test dataset
- rule scorer as a baseline/safety signal
- reason-aware ML scorer
- canonical evidence engine
- lightweight relationship graph
- economics calculation
- deterministic policy authority
- SQLite audit/idempotency
- draft-only Razorpay-compatible adapter
- existing regression suite and domain tests
- calibration and leakage evaluation
- feedback storage outside the critical decision path

## Simplified

- live model path reduced to one reason-aware Logistic Regression estimator
- HGB retained only as an offline challenger
- hybrid probability retained only for offline comparison
- evidence status logic consolidated in `evidence.py`
- economics object no longer exposes a second action recommendation
- sensitivity analysis delegates to the canonical policy function
- Streamlit experience consolidated to `apps/app_deployed.py`
- benchmark and metrics execute the same canonical engine as the API

## Added

- `CanonicalDecision` result object
- bounded read-only counterfactual analysis
- focused adversarial/safety regression tests
- fair six-strategy benchmark
- local end-to-end latency benchmark
- artifact compatibility metadata
- explicit baseline benchmark artifact and candidate comparison

## Decisions not taken

No new database technology, queue, service mesh, graph database, model-serving infrastructure, LLM, or frontend framework was introduced. The existing stack was sufficient for the required behavior.

No claim of temporal robustness was added because the available dates are synthetic.
