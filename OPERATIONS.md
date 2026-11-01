# Operations & Production Runbook

This runbook covers deployment, monitoring, secret management, audit log verification, and capacity planning for `chargeback-risk-engine`.

---

## 1. Production Deployment Runbook

### 1.1 Architecture & Resource Sizing

`chargeback-risk-engine` is packaged as a stateless containerized FastAPI service with a durable SQLite Write-Ahead Log (WAL) audit volume.

| Component | Minimum Sizing | Recommended Production Sizing |
|---|---|---|
| **CPU** | 0.5 vCPU | 2.0 vCPU |
| **Memory** | 256 MB RAM | 1.0 GB RAM |
| **Storage** | 1.0 GB persistent volume | 20.0 GB NVMe persistent volume |
| **Operating System** | Alpine / Debian Slim | Alpine 3.19+ / distroless |

### 1.2 Docker Deployment

Build and run using the optimized multi-stage `Dockerfile`:

```bash
# Build the production image
docker build -t chargeback-risk-engine:1.0.0 .

# Run with environment configuration
docker run -d \
  --name chargeback-service \
  -p 8000:8000 \
  -v chargeback_data:/app/data \
  -e CHARGEBACK_ENV=production \
  -e CHARGEBACK_API_KEYS="prod-key-1:secret_alpha_99:admin,client-key-1:secret_beta_88:write" \
  -e CHARGEBACK_ANCHOR_SECRET="production_hmac_anchor_secret_32bytes" \
  -e CHARGEBACK_RATE_LIMIT_RPS=50 \
  -e CHARGEBACK_MAX_BODY_BYTES=65536 \
  -e CHARGEBACK_REQUEST_TIMEOUT_SECONDS=5.0 \
  chargeback-risk-engine:1.0.0
```

### 1.3 Docker Compose Deployment

A complete production-ready stack is defined in `docker-compose.yml`:

```bash
# Start service stack
docker compose up -d

# Verify service logs
docker compose logs -f api
```

### 1.4 Kubernetes Deployment & Probes

For Kubernetes deployments, configure container probes:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chargeback-risk-engine
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: chargeback-api
        image: chargeback-risk-engine:1.0.0
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /readyz
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
        volumeMounts:
        - name: audit-volume
          mountPath: /app/data
      volumes:
      - name: audit-volume
        persistentVolumeClaim:
          claimName: chargeback-audit-pvc
```

---

## 2. Prometheus Observability & Metrics Reference

The service exports Prometheus-compatible metrics at `GET /metrics`.

### Metric Definitions

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `chargeback_decisions_total` | Counter | `action`, `reason_code` | Cumulative number of decisions executed, segmented by financial action (`AUTO-CONTEST`, `HUMAN-REVIEW`, `ACCEPT-LOSS`) and dispute reason code. |
| `chargeback_decision_duration_seconds` | Histogram | `action` | Request latency distribution for decision evaluation in seconds. |
| `chargeback_audit_writes_total` | Counter | `status` | Total SQLite audit trail append attempts (`success`, `failure`). |
| `chargeback_rate_limit_exceeded_total` | Counter | None | Total requests rejected with HTTP 429 due to client rate limit violations. |
| `chargeback_evidence_score` | Summary | `reason_code` | Running distribution of evidence quality scores $\in [0.0, 1.0]$. |

### Prometheus Alerting Rules Example

```yaml
groups:
- name: chargeback-engine-alerts
  rules:
  - alert: HighReviewRate
    expr: rate(chargeback_decisions_total{action="HUMAN-REVIEW"}[10m]) / rate(chargeback_decisions_total[10m]) > 0.85
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "Chargeback human review rate exceeded 85%"

  - alert: AuditWriteFailures
    expr: increase(chargeback_audit_writes_total{status="failure"}[5m]) > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "SQLite audit trail write failures detected"
```

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
3. **Reload Configuration**: Update Kubernetes secret or restart container. The service accepts both keys simultaneously.
4. **Migrate Upstream Clients**: Update client services to send `X-API-Key: prod-2026-v2:secret_new_value:write`.
5. **Retire Old Key**: Once telemetry indicates zero traffic on `prod-2026-v1`, remove the old key from `CHARGEBACK_API_KEYS` and re-deploy.

---

## 4. Audit Log Anchoring & Verification Runbook

### 4.1 CLI Audit Verification

Verify the cryptographic SHA-256 integrity of any persistent audit database:

```bash
# Verify the default or specified database
chargeback-cli verify-audit --db data/audit_log.db
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

To defend against whole-log rollback or deletion by a host intruder:

1. Configure `CHARGEBACK_ANCHOR_SECRET` with an HMAC secret.
2. Query the anchor endpoint using an `admin` credential:
   ```bash
   curl -H "X-API-Key: admin-key:admin-secret:admin" http://localhost:8000/audit/head/anchor
   ```
3. The endpoint returns:
   ```json
   {
     "head_hash": "9f83ac6...",
     "timestamp": "2026-11-01T12:00:00Z",
     "signature": "hmac_sha256_signature_hex"
   }
   ```
4. Configure an automated hourly cron job to store this signed anchor in an external append-only log, S3 bucket with Object Lock, or ledger.

---

## 5. Load Testing & Measured Capacity

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

### Suggested Production SLOs

The following suggested service level objectives (SLOs) are informed by the measured benchmark results and can be tuned for production hardware configurations:

- **Target Availability**: $\ge 99.9\%$ successful decisions (excluding client 4xx authentication/validation errors).
- **Target Latency (2 vCPU reference)**: P50 $< 1,500$ ms, P95 $< 3,000$ ms under peak 16-worker concurrency.
- **Audit Logging Reliability**: $100\%$ tamper-evident SHA-256 chain persistence ($0$ silent write drop).
- **Rate Limit Resilience**: Max 60 req/min per unprivileged client key (configurable via `CHARGEBACK_RATE_LIMIT`).
