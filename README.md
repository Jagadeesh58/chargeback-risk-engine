# Chargeback Risk Engine

Production-minded **AI chargeback risk and decision engine** for the Razorpay Buildathon.

> **AI proposes. Evidence verifies. Economics prioritizes. Policy decides.**

## Repository structure

```text
chargeback-risk-engine/
├── chargeback_risk_engine/      # reusable application/domain package
│   ├── engine/                  # hybrid, evidence, graph, economics, explainability
│   └── *.py                     # scoring, policy, audit, ML, models, adapters
├── apps/                        # FastAPI API + Streamlit dashboard
├── training/                    # reproducible model and temporal evaluation
├── scripts/                     # demo, benchmark, data generation, leakage checks
├── tests/                       # complete automated test suite
├── data/                        # synthetic train/dev/test data
├── artifacts/                   # reproducible evaluation outputs
├── docs/                        # architecture audit and evaluation report
├── README.md
├── ARCHITECTURE.md
├── SECURITY.md
├── DEMO.md
├── CONTRIBUTING.md
├── INTERVIEW_PREP.md
├── pyproject.toml
└── requirements.txt
```

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
python scripts/generate_data.py --out-dir data   # or: make data
pytest -q
python scripts/demo.py
python training/train_models.py
python training/evaluate_temporal.py
python scripts/benchmark.py
```

Run the API:

```bash
uvicorn apps.api:app --reload
```

Run the dashboard:

```bash
streamlit run apps/dashboard.py
```

See [DEMO.md](DEMO.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md) for details.

## Safety model

Machine-learning outputs never directly execute financial actions. Final routing is controlled by deterministic policy gates covering evidence quality, uncertainty, expected value, monetary exposure, retries/idempotency, and safe fallback behavior.

## Razorpay integration status

The repository includes a Razorpay-compatible adapter and mock/test behavior. **Live production connectivity is not claimed.** Credentials, when used for future test-mode work, must come from environment variables.
