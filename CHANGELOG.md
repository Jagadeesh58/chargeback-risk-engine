# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## Unreleased

### Added
- **Readiness Probe and Integrity Checks**: Added `/readyz` probe to verify database connectivity, JSON model loading and SHA-256 checksum verification, audit chain head readability, and cryptographic verification of the last N rows (returns 503 Service Unavailable with machine-readable diagnostic errors on failure).
- **Authenticated Metrics**: Secured `/metrics` Prometheus endpoint in production mode with API key authentication or dedicated `CHARGEBACK_METRICS_KEY` (returns 401 Unauthorized without credentials).
- **Measured Production Load Test Benchmark**: Added real ASGI load testing across 1,000, 10,000, and 100,000 pre-seeded audit/graph rows with 16 concurrent workers, demonstrating sub-linear graph retrieval scaling (~35 ms 2-hop CTE execution; 0.67x P95 ratio at 100k vs 1k) recorded in `artifacts/load_test_report.json` and `docs/OPERATIONS.md`.
- **Prometheus Alert Rules**: Added `deploy/alert_rules.yml` defining production firing rules for error rate surges, latency spikes, rate limiting, and audit integrity verification failures, verified against live metric names in `tests/test_prometheus_alerts.py`.
- **Examples & Quickstart**: Added `examples/request_verified.json`, `examples/request_unverified.json`, `examples/python_client.py`, and `examples/quickstart.sh`, backed by automated verification in `tests/test_examples.py`.
- **Production Hardening Test Suite**: Added automated tests covering production-mode request handling, replay conflicts, oversized body rejection, unauthenticated request handling, audit tampering detection, and concurrent writes.
- **Test Isolation Enforcement**: Enforced test isolation ensuring automated test runs never modify tracked repository artifacts in place.
- **Packaging Verification**: Added `tests/test_packaging_deps.py` verifying AST-based third-party imports match `pyproject.toml`, version synchronization, and single-source package metadata.
- **Unified Operational CLI (`chargeback-cli`)**: Introduced entry point supporting `serve`, `verify-audit`, `train`, and `evaluate` subcommands.
- **Settings and key management**: Added `pydantic-settings` integration with support for multi-key authentication (`CHARGEBACK_API_KEYS`), zero-downtime key rotation, and role-based access control (`read`, `write`, `admin`).
- **Code of Conduct**: Added Contributor Covenant 2.1 in `CODE_OF_CONDUCT.md`.

### Changed
- **Scikit-Learn Version Compatibility**: Constrained runtime dependency to `scikit-learn>=1.9,<1.10` and trained model artifact under 1.9.1. Added major.minor compatibility checking in the model loader with explicit instructions to retrain via `make train` whenever scikit-learn's minor version changes.
- **Documentation and Safety Framing**: Softened regulatory assertions, documented data privacy architectural design notes, and linked covering safety tests across documentation.
- **Documentation Consolidation**: Consolidated repository documentation into `docs/` (`ARCHITECTURE.md`, `DECISIONS.md`, `MODEL_CARD.md`, `EVALUATION.md`, `OPERATIONS.md`, `THREAT_MODEL.md`, `DATA_DICTIONARY.md`). Merged baseline and evaluation protocol into `docs/EVALUATION.md`. Folded "Why Not Contest Everything" into `docs/ARCHITECTURE.md`.
- **Performance Documentation**: Replaced unmeasured throughput and latency targets in `docs/OPERATIONS.md` with empirical load test tables and suggested example SLOs.
- **Dependency Segregation**: Slimmed core dependencies in `pyproject.toml` to runtime necessities (`fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `scikit-learn`, `numpy`, `pandas`, `prometheus-client`), moving `matplotlib` to optional extra `[reports]`.
- **Eliminated Arbitrary Deserialization**: Removed all pickle-based model weights in favor of transparent, human-readable JSON parameters (`ml_scorer_model.json`) verified against SHA-256 sidecar hashes at startup.
- **Currency & Economic Alignment**: Standardized all monetary figures across documentation, scripts, and tests to Indian Rupees (`₹`), enforcing symmetric lost-contest penalties.
- **CI Hardening**: Enhanced `.github/workflows/ci.yml` with blocking `pip-audit`, secret scanning, markdown link checking, wheel building, and fresh-venv clean install verification.

### Fixed
- **Candidate Benchmark Reproducibility**: Fixed non-deterministic candidate benchmark execution to ensure byte-exact reproducibility across independent test runs.
- **Audit Tamper Detection**: Ensured cryptographic failure detection and immediate 503 readiness failure when historical records are modified or truncated.
- **Graph Merchant Linkage**: Eliminated buyer-side lockouts caused by multi-dispute merchant identifier sharing.
- **SQLite Subquery Rowid Execution**: Fixed SQLite outer query rowid resolution when reading recent audit log decisions.
