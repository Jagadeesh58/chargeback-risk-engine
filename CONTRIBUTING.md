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
   Before submitting changes, ensure all verification gates pass cleanly:
   ```bash
   ruff check .
   ruff format --check .
   mypy chargeback_risk_engine
   pytest -q
   python scripts/verify_release.py
   ```
