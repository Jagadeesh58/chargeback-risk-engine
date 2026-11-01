# Deployment and Operations Notes

This runbook covers deployment, environment configuration, monitoring, secret management, backup/restore, audit log verification, incident response, and capacity planning for `chargeback-risk-engine`.

---

## 1. Production Deployment Runbook

### 1.1 Architecture & Resource Sizing

`chargeback-risk-engine` is packaged as a stateless FastAPI service with a durable SQLite Write-Ahead Log (WAL) audit volume.

| Component | Minimum Sizing | Recommended Production Sizing |
|---|---|---|
| **CPU** | 0.5 vCPU | 2.0 vCPU |
| **Memory** | 256 MB RAM | 1.0 GB RAM |
| **Storage** | 1.0 GB persistent volume | 20.0 GB NVMe persistent volume |
| **Operating System** | Linux (Debian, Ubuntu, Alpine) / Windows Server | Linux with NVMe storage |

### 1.2 Production ASGI Service Deployment

Deploy the engine using Uvicorn or a process supervisor (e.g., systemd, supervisord) directly in a dedicated Python environment:

```bash
# 1. Install production package in a virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install .

# 2. Configure production environment
export CHARGEBACK_ENV=production
export CHARGEBACK_API_KEY="prod-admin-secret-at-least-32-chars-long"
export CHARGEBACK_API_KEYS="prod-key-1:secret_alpha_99:admin,client-key-1:secret_beta_88:write"
export CHARGEBACK_AUDIT_DB_PATH="/var/lib/chargeback/audit_log.db"
export CHARGEBACK_ANCHOR_SECRET="production_hmac_anchor_secret_32bytes"
export CHARGEBACK_RATE_LIMIT=120
export CHARGEBACK_REQUEST_TIMEOUT_SECONDS=5.0

# 3. Launch with Uvicorn
uvicorn chargeback_risk_engine.api:app --host 0.0.0.0 --port 8000 --workers 2
```

### 1.3 Health & Readiness Probes

The engine provides dedicated probe endpoints for health checkers and load balancers:

- **Liveness Probe (`/healthz`)**:
  Returns HTTP 200 confirming the process is alive.
  ```bash
  curl -f http://localhost:8000/healthz
  ```

- **Readiness Probe (`/readyz`)**:
  Verifies database connectivity (`SELECT 1`), model artifact integrity, audit head hash readability, and cryptographic integrity of the last N audit rows. Returns HTTP 200 when ready or HTTP 503 if any check fails:
  ```bash
  curl -f http://localhost:8000/readyz
  ```

---

## 2. Environment Variables Reference

| Variable | Type | Default | Production Requirement | Description |
|---|---|---|---|---|
| `CHARGEBACK_ENV` | string | `production` | **Required** (`production`) | Application runtime mode (`production`, `development`, `demo`). |
| `CHARGEBACK_DEBUG` | boolean | `false` | Must be `false` | Debug mode; forbidden in production mode. |
| `CHARGEBACK_API_KEY` | string | `""` | **Required** (>= 32 chars) | Default admin API secret key. |
| `CHARGEBACK_API_KEYS` | string | `""` | Optional | Multi-key rotation mapping (`id:secret:role,...`). |
| `CHARGEBACK_METRICS_KEY` | string | `""` | Optional | Dedicated secret key for scraping `/metrics` in production. |
| `CHARGEBACK_AUDIT_DB_PATH` | string | `data/audit_log.db` | **Required** (Absolute path) | Path to persistent SQLite audit database. |
| `CHARGEBACK_DB_PATH` | string | `""` | Legacy alias | Backwards-compatible alias for `CHARGEBACK_AUDIT_DB_PATH`. |
| `CHARGEBACK_MODEL_PATH` | string | `artifacts/ml_scorer_model.json` | Default | Safe JSON logistic regression model file. |
| `CHARGEBACK_MODEL_SHA256` | string | Sidecar `.sha256` | **Required** (Sidecar or env) | SHA-256 digest of approved model artifact. |
| `CHARGEBACK_REQUIRE_MODEL_HASH` | boolean | `false` | Recommended (`true`) | Enforce model hash verification strictly. |
| `CHARGEBACK_RATE_LIMIT` | integer | `60` | Optional | Requests per minute per client key (0 to disable). |
| `CHARGEBACK_REQUEST_TIMEOUT_SECONDS` | float | `5.0` | Default (`5.0`s) | Maximum request processing deadline. |
| `CHARGEBACK_MAX_BODY_BYTES` | integer | `65536` | Default (64 KB) | HTTP request payload size cap. |
| `CHARGEBACK_CORS_ORIGINS` | string | `""` | Explicit list (no `*`) | Allowed Cross-Origin Resource Sharing origins. |
| `CHARGEBACK_READYZ_AUDIT_ROWS` | integer | `100` | Default (`100`) | Number of recent audit records checked by `/readyz`. |
| `CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE` | boolean | `false` | Must be `false` | Allows unverified evidence items in development mode only. |
| `CHARGEBACK_MAX_EVIDENCE_AGE_DAYS` | float | `365.0` | Default (`365.0`) | Maximum age in days for evidence item timestamp validity. |
| `CHARGEBACK_ALLOW_TEST_CLIENT_HEADER` | boolean | `false` | Must be `false` | Allow test client IP spoofing header; dev only. |
| `CHARGEBACK_ANCHOR_SECRET` | string | `""` | Optional | Shared HMAC secret for signing external audit head anchors. |

---

## 3. Multi-Key Rotation Procedure

The engine supports zero-downtime key rotation through the `CHARGEBACK_API_KEYS` setting.

### Key Format
`key_id:secret:role[,key_id:secret:role,...]`

Roles:
- `read`: Read-only queries and advisory scoring (`/health`, `/score`).
- `write`: Decision processing (`/decision`).
- `admin`: Operational inspection (`/audit/verify`, `/audit/head/anchor`, `/metrics`).

### Rotation Protocol

1. **Generate New Key**: Generate a cryptographically secure 32-byte secret for the new key (e.g. `prod-2026-v2:secret_new_value:write`).
2. **Deploy Dual-Key Configuration**: Add the new key alongside the active key:
   ```bash
   CHARGEBACK_API_KEYS="prod-2026-v1:old_secret:write,prod-2026-v2:secret_new_value:write"
   ```
3. **Reload Configuration**: Update environment configuration or restart the service process. The service accepts both keys simultaneously.
4. **Migrate Upstream Clients**: Update client services to send `X-API-Key: prod-2026-v2:secret_new_value:write`.
5. **Retire Old Key**: Once telemetry indicates zero traffic on `prod-2026-v1`, remove the old key from `CHARGEBACK_API_KEYS` and re-deploy.

---

## 4. Audit Log Anchoring, Backup & Verification Runbook

### 4.1 CLI Audit Verification

Verify the cryptographic SHA-256 integrity of any persistent audit database:

```bash
# Verify the default or specified database
chargeback-cli verify-audit --db /var/lib/chargeback/audit_log.db
```

Expected JSON response:
```json
{
  "valid": true,
  "checked": 1420,
  "head_hash": "a1b2c3d4e5f6...7890",
  "error": null
}
```

If any row has been retroactively modified, inserted, or deleted, `valid` will be `false` with the offending `dispute_id` and position reported in `error`.

### 4.2 External Head Anchoring

To defend against whole-log rollback or deletion by an attacker:

1. Configure `CHARGEBACK_ANCHOR_SECRET` with an HMAC secret.
2. Query the anchor export CLI or HTTP endpoint:
   ```bash
   # CLI export utility
   python scripts/export_audit_head.py --db /var/lib/chargeback/audit_log.db --out /var/log/audit_head.json
   ```
3. Automated hourly cron example:
   ```cron
   0 * * * * python /app/scripts/export_audit_head.py --db /var/lib/chargeback/audit_log.db --out /var/log/chargeback_anchors/head_$(date +\%Y\%m\%d\%H).json
   ```

### 4.3 Backup & Restore Procedure

SQLite Write-Ahead Logging allows safe live backups using the SQLite VACUUM INTO command:

```bash
# Perform live consistent backup
sqlite3 /var/lib/chargeback/audit_log.db "VACUUM INTO '/backups/audit_$(date +%Y%m%d).db';"

# Verify integrity of backup archive
chargeback-cli verify-audit --db /backups/audit_$(date +%Y%m%d).db
```

---

## 5. Prometheus Observability & Metrics Reference

The service exports Prometheus-compatible metrics at `GET /metrics`. In production mode, requests must present a valid API key or `CHARGEBACK_METRICS_KEY`.

### Metric Definitions

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `chargeback_decisions_total` | Counter | `action`, `reason_code` | Cumulative decisions executed, segmented by financial action (`AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS`) and dispute reason code. |
| `chargeback_decision_duration_seconds` | Histogram | `action` | Request latency distribution for decision evaluation in seconds. |
| `chargeback_audit_writes_total` | Counter | `status` | Total SQLite audit trail append attempts (`success`, `replay`, `conflict`, `error`). |
| `chargeback_rate_limit_exceeded_total` | Counter | `key_id` | Total requests rejected with HTTP 429 due to client rate limit violations. |
| `chargeback_evidence_scores` | Histogram | `reason_code` | Running distribution of evidence quality scores $\in [0.0, 1.0]$. |

---

## 6. Incident Runbook

### Incident 1: Audit Chain Verification Failure
- **Symptoms**: `/readyz` returns 503 with `"audit_chain": "error: Hash chain verification mismatch"`.
- **Diagnosis**: Run `chargeback-cli verify-audit --db $CHARGEBACK_AUDIT_DB_PATH`. Identify the reported `failed_dispute_id`.
- **Mitigation**:
  1. Freeze writes by placing upstream traffic in human review queue.
  2. Compare database against external signed head anchors (`scripts/export_audit_head.py`) to isolate the exact point of tampering.
  3. If corruption is physical/hardware-related, restore from the latest verified VACUUM snapshot.

### Incident 2: Model Hash Mismatch
- **Symptoms**: Service startup crashes with `RuntimeError: CHARGEBACK_MODEL_SHA256 mismatch` or `/readyz` returns 503.
- **Diagnosis**: Check if `ml_scorer_model.json` was updated without regenerating `ml_scorer_model.json.sha256`.
- **Mitigation**: Verify provenance of model file. If retrained legitimately, regenerate sidecar digest with `python -c "import hashlib, sys; print(hashlib.sha256(open('artifacts/ml_scorer_model.json','rb').read()).hexdigest(), file=open('artifacts/ml_scorer_model.json.sha256','w'))"`.

### Incident 3: AI Analyst Outage / Timeout
- **Symptoms**: Advisory notes timeout or fail.
- **Diagnosis**: Check log entries for `ai_analyst` module.
- **Safety Invariant**: The engine fails closed. If the AI analyst times out or errors, the pipeline falls back to deterministic rule scoring; decision authority remains solely with `policy.py`.

### Incident 4: Rate Limiting Saturation (HTTP 429)
- **Symptoms**: Upstream callers receive HTTP 429. Prometheus metric `chargeback_rate_limit_exceeded_total` spiking.
- **Mitigation**:
  1. Review client key in alert label.
  2. Adjust `CHARGEBACK_RATE_LIMIT` environment variable if traffic surge is legitimate, or scale workers. Note: the built-in limiter is per-process; for multi-node deployments, terminate rate limiting at the reverse proxy (e.g. NGINX / Cloudflare).

---

## 7. Load Testing & Measured Capacity

Use the included load testing utility (`scripts/load_test.py`) to benchmark latency and throughput against a live production ASGI stack (Uvicorn, SQLite audit logging with SHA-256 chaining, authentication enabled, and full evidence provenance verification):

```bash
# Execute multi-scale load test across 1k, 10k, and 100k pre-seeded audit/graph rows
python scripts/load_test.py --duration 30 --concurrency 16 --scales 1000,10000,100000
```

### Measured Performance Baseline (Synthetic Data)

> [!NOTE]
> All measurements below were generated by `scripts/load_test.py` on the benchmark reference hardware:
> **OS/Platform**: Windows (Intel64 Family 6 Model 58 Stepping 9, 2 logical cores), Python 3.11.9, 16 concurrent workers, sustained 30-second duration per scale.
> These numbers are specific to this test environment and demonstrate bounded, sub-linear neighborhood query scaling.

<!-- LOAD_TEST_RESULTS_START -->
| Pre-seeded Rows | Concurrency | Duration (s) | Total Requests | Error Count | Throughput (req/s) | P50 Latency (ms) | P95 Latency (ms) | P99 Latency (ms) | Mean Latency (ms) |
|---|---|---|---|---|---|---|---|---|---|
| 1,000 | 16 | 30.43 | 355 | 0 | 11.67 | 1202.20 | 2265.38 | 2923.35 | 1296.76 |
| 10,000 | 16 | 30.95 | 370 | 0 | 11.95 | 1202.66 | 2584.41 | 3632.99 | 1302.03 |
| 100,000 | 16 | 30.46 | 445 | 0 | 14.61 | 1087.39 | 1513.09 | 1989.91 | 1085.19 |
<!-- LOAD_TEST_RESULTS_END -->

**Sub-linear Scaling Verification**:
- Bounded neighborhood 2-hop CTE query ensures graph traversal cost remains bounded regardless of audit history depth.
- Ratio of P95 latency at 100,000 rows to 1,000 rows: **0.67x** ($\le 2.0\text{x}$ requirement verified).
- Error rate under sustained load across all database scales: **0.00%**.

### Suggested SLO Examples (Non-Binding Examples)

The following service level objectives (SLOs) are provided as illustrative operational examples informed by the benchmark measurements above, not performance guarantees:

- **Availability Target**: ≥ 99.9% successful decisions (excluding client 4xx authentication/validation errors).
- **Latency Target (Reference 2-Core Hardware)**: P50 < 1,500 ms, P95 < 3,000 ms under peak 16-worker concurrency.
- **Audit Integrity Limitation & Mitigation**: The hash chain detects modification or truncation of historical records. However, an actor with direct database write access can recompute the chain hashes; periodic external head anchoring (`scripts/export_audit_head.py`) to an independent append-only log is the necessary mitigation.
- **Rate Limiting Target**: Default 60 req/min per client key (configurable via `CHARGEBACK_RATE_LIMIT`).
