# Contributing Guidelines

Thank you for contributing to `chargeback-risk-engine`.

## Development Workflow

1. **Branching**: Create a focused branch: `git checkout -b feature/your-feature`.
2. **Environment Setup**: Install dependencies in editable mode with development tools:
   ```bash
   pip install -e ".[dev]"
   pre-commit install
   ```
3. **Core Architectural Invariant**:
   - Machine learning, graph clustering, and AI analysts provide advisory signals only.
   - Only `chargeback_risk_engine.policy.decide()` may select financial actions (`AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS`).
   - Every uncertain or invalid input must fail closed to `HUMAN-REVIEW`, never `AUTO-CONTEST`.
4. **Data Discipline**:
   - Do not tune or optimize thresholds against `data/test.csv`; use `data/dev.csv` for experimentation.
   - Express all monetary figures strictly in Indian Rupees (`₹`).
5. **Quality Verification**:
   Before submitting changes, ensure all verification gates match CI:
   ```bash
   ruff check .
   ruff format --check .
   mypy chargeback_risk_engine
   pytest --cov=chargeback_risk_engine --cov-report=term-missing
   python scripts/generate_report.py
   git diff --exit-code -- README.md artifacts docs ':!docs/*.png'
   make verify
   pip-audit
   python -m build
   twine check dist/*
   ```

## Useful Makefile Targets

- `make check`: Run full linting, type-checking, test suite, and drift verification.
- `make test`: Run pytest suite.
- `make regen`: Regenerate all benchmark reports and evaluation artifacts.
- `make train`: Train model weights and update JSON artifact.
- `make data`: Regenerate synthetic train/dev/test datasets.
- `make policy-optimize`: Optimize deterministic decision thresholds against development data.
- `make release-zip`: Create clean source distribution archive from HEAD.
- `make api`: Launch local development API server with auto-reload.
