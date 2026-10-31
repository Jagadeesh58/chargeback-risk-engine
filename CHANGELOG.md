# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-11-01

### Added
- **Unified Operational CLI (`chargeback-cli`)**: Introduced entry point supporting `serve`, `verify-audit`, `train`, and `evaluate` subcommands.
- **Enterprise Settings & Key Management**: Added `pydantic-settings` integration with support for multi-key authentication (`CHARGEBACK_API_KEYS`), zero-downtime key rotation, and role-based access control (`read`, `write`, `admin`).
- **Production Observability**: Added `/metrics` Prometheus endpoint exposing decision counts, evaluation durations, audit write counters, and rate-limiting metrics.
- **Production Readiness Probes**: Implemented `/healthz` (liveness) and `/readyz` (readiness) endpoints with startup configuration and database connectivity verification.
- **SQLite Audit Store Protocol**: Standardized `AuditStore` protocol with Write-Ahead Logging (`WAL`), serialized transactions (`_AUDIT_WRITE_LOCK`), automated versioned schema migrations, and external HMAC-SHA256 head anchoring.
- **Container Infrastructure**: Added multi-stage production `Dockerfile` and `docker-compose.yml` configuration.
- **Synthetic Load Testing Suite**: Added `scripts/load_test.py` for concurrent throughput and latency benchmarking.
- **Evaluation Validity Framework**: Implemented `scripts/run_ablations.py` testing 6 ablation variants, 1,000 bootstrap resamples with 95% confidence intervals, and `scripts/evaluate_real_data.py` for evaluating external dispute datasets.
- **Type Annotations**: Shipped `chargeback_risk_engine/py.typed` and achieved 100% strict `mypy` type checking across all source modules.

### Changed
- **Eliminated Arbitrary Deserialization**: Removed all pickle-based model weights in favor of transparent, human-readable JSON parameters (`ml_scorer_model.json`) verified against SHA-256 sidecar hashes at startup.
- **Currency & Economic Alignment**: Standardized all monetary figures across documentation, scripts, and tests to Indian Rupees (`₹`), enforcing symmetric lost-contest penalties.
- **Documentation Condensation**: Streamlined `README.md` to under 250 lines with a comprehensive decision table, architecture diagram, and empirical results snapshot.
- **Enhanced Security Middleware**: Integrated streaming request body size caps (64 KB) and pre-parsing rate limiting.

### Fixed
- **Candidate Benchmark Reproducibility**: Fixed non-deterministic candidate benchmark execution to ensure byte-exact reproducibility across independent test runs.
- **FastAPI Request Timeout Handling**: Configured resilient request timeouts to prevent gateway timeouts under test tracing overhead.
- **Audit Tamper Detection**: Ensured cryptographic failure detection when historical records are modified or truncated.
- **Graph Merchant Linkage**: Eliminated buyer-side lockouts caused by multi-dispute merchant identifier sharing.
