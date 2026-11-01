"""scripts/load_test.py — Production ASGI load test harness across 1k/10k/100k database scales.

Measures realistic p50, p95, p99 latency and throughput against a live Uvicorn ASGI server
with production settings: API key authentication enabled, cryptographic audit hashing enabled,
and full evidence provenance validation.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from chargeback_risk_engine.audit_log import _run_migrations
from chargeback_risk_engine.paths import ARTIFACTS_DIR

API_KEY = "test-prod-key-32-chars-long-minimum-val"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_database(db_path: str, n_rows: int) -> None:
    """Pre-seed SQLite database with n_rows decisions and graph entity relationships."""
    conn = sqlite3.connect(db_path)
    try:
        _run_migrations(conn)
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = MEMORY")

        # Cluster entities so graph relationships exist
        cluster_cardinality = max(1, n_rows // 10)
        decisions = []
        entities = []
        for i in range(n_rows):
            d_id = f"hist_{n_rows}_{i}"
            cust_id = f"cust_{i % cluster_cardinality}"
            decisions.append(
                (
                    d_id,
                    "item_not_received",
                    3500.0,
                    0.75,
                    "AUTO-CONTEST",
                    "compelling_evidence_match",
                    2475.0,
                    "{}",
                    "2026-10-31T00:00:00Z",
                    "rules-v1",
                    "features-v1",
                    "policy-v1",
                    json.dumps({"customer_id": cust_id}),
                    "{}",
                    f"req_{i}",
                    0.75,
                    "0" * 64,
                    "0" * 64,
                    "0" * 64,
                    "client-1",
                )
            )
            entities.append((d_id, "customer_id", cust_id, 3500.0))

        conn.executemany(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            decisions,
        )
        conn.executemany("INSERT INTO graph_entities VALUES (?, ?, ?, ?)", entities)
        conn.commit()
    finally:
        conn.close()


def _run_single_request(port: int, dispute_id: str, cust_id: str) -> tuple[bool, float, int]:
    url = f"http://127.0.0.1:{port}/decision"
    payload = {
        "dispute_id": dispute_id,
        "payment_id": f"pay_{dispute_id}",
        "reason_code": "item_not_received",
        "amount": 4200.0,
        "customer_id": cust_id,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
        "has_tracking_number_source": "carrier_api",
        "has_tracking_number_timestamp": "2026-10-31T12:00:00Z",
        "has_delivery_confirmation_source": "carrier_api",
        "has_delivery_confirmation_timestamp": "2026-10-31T12:00:00Z",
        "has_signature_confirmation_source": "carrier_api",
        "has_signature_confirmation_timestamp": "2026-10-31T12:00:00Z",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return (resp.status == 200, elapsed, resp.status)
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return (False, elapsed, e.code)
    except Exception:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return (False, elapsed, 500)


def _bootstrap_latency_cis(
    latencies: list[float],
    n_boot: int = 1000,
    seed: int = 42,
) -> dict[str, list[float]]:
    """Compute 95% bootstrap confidence intervals for p50, p95, and p99 latency."""
    if not latencies:
        return {
            "latency_p50_ci_95": [0.0, 0.0],
            "latency_p95_ci_95": [0.0, 0.0],
            "latency_p99_ci_95": [0.0, 0.0],
        }
    import numpy as np

    arr = np.array(latencies, dtype=float)
    n = len(arr)
    rng = np.random.default_rng(seed)
    boot_idx = rng.integers(0, n, size=(n_boot, n))
    boot_samples = arr[boot_idx]
    boot_percs = np.percentile(boot_samples, [50.0, 95.0, 99.0], axis=1)

    return {
        "latency_p50_ci_95": [
            round(float(np.percentile(boot_percs[0], 2.5)), 2),
            round(float(np.percentile(boot_percs[0], 97.5)), 2),
        ],
        "latency_p95_ci_95": [
            round(float(np.percentile(boot_percs[1], 2.5)), 2),
            round(float(np.percentile(boot_percs[1], 97.5)), 2),
        ],
        "latency_p99_ci_95": [
            round(float(np.percentile(boot_percs[2], 2.5)), 2),
            round(float(np.percentile(boot_percs[2], 97.5)), 2),
        ],
    }


def benchmark_scale(
    n_rows: int,
    concurrency: int,
    duration: float,
    port: int,
    db_path: str,
) -> dict[str, Any]:
    print(f"\n[LoadTest] Pre-seeding database with {n_rows:,} rows...")
    t_seed = time.perf_counter()
    _seed_database(db_path, n_rows)
    print(f"[LoadTest] Seed completed in {time.perf_counter() - t_seed:.2f} s")

    # Warmup (10 requests, excluded from stats)
    for w in range(10):
        _run_single_request(port, f"warmup_{n_rows}_{w}", f"cust_warm_{w}")

    print(
        f"[LoadTest] Running test: scale={n_rows:,} rows, concurrency={concurrency}, target_duration={duration:.1f} s..."
    )
    latencies: list[float] = []
    success_count = 0
    error_count = 0

    stop_event = threading.Event()
    start_time = time.perf_counter()
    req_counter = 0

    def worker_loop(worker_id: int):
        nonlocal req_counter, success_count, error_count
        while not stop_event.is_set():
            idx = req_counter
            req_counter += 1
            d_id = f"bench_{n_rows}_{worker_id}_{idx}_{uuid.uuid4().hex[:6]}"
            cust_id = f"cust_{idx % max(1, n_rows // 10)}"
            ok, lat, code = _run_single_request(port, d_id, cust_id)
            latencies.append(lat)
            if ok:
                success_count += 1
            else:
                error_count += 1
            if time.perf_counter() - start_time >= duration:
                stop_event.set()
                break

    threads = []
    for wid in range(concurrency):
        t = threading.Thread(target=worker_loop, args=(wid,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    total_wall = time.perf_counter() - start_time
    total_reqs = len(latencies)
    throughput = round(total_reqs / total_wall, 2) if total_wall > 0 else 0.0

    sorted_lats = sorted(latencies)
    p50 = round(statistics.median(sorted_lats), 2) if sorted_lats else 0.0
    p95 = round(sorted_lats[int(0.95 * len(sorted_lats))], 2) if sorted_lats else 0.0
    p99 = round(sorted_lats[int(0.99 * len(sorted_lats))], 2) if sorted_lats else 0.0
    mean_lat = round(statistics.mean(sorted_lats), 2) if sorted_lats else 0.0

    cis = _bootstrap_latency_cis(latencies)

    print(f"[LoadTest] Results for scale={n_rows:,}:")
    print(f"  Requests:   {total_reqs} ({throughput:.1f} req/s)")
    print(f"  Success:    {success_count} | Errors: {error_count}")
    print(f"  Latency:    p50={p50} ms, p95={p95} ms, p99={p99} ms (mean={mean_lat} ms)")
    print(f"  95% CIs:    p50={cis['latency_p50_ci_95']}, p95={cis['latency_p95_ci_95']}, p99={cis['latency_p99_ci_95']}")

    return {
        "pre_seeded_rows": n_rows,
        "concurrency": concurrency,
        "duration_seconds": round(total_wall, 2),
        "total_requests": total_reqs,
        "successful_requests": success_count,
        "error_count": error_count,
        "throughput_rps": throughput,
        "latency_p50_ms": p50,
        "latency_p50_ci_95": cis["latency_p50_ci_95"],
        "latency_p95_ms": p95,
        "latency_p95_ci_95": cis["latency_p95_ci_95"],
        "latency_p99_ms": p99,
        "latency_p99_ci_95": cis["latency_p99_ci_95"],
        "latency_mean_ms": mean_lat,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Chargeback Risk Engine Load Test Harness")
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Test duration in seconds per scale (default: 60.0)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=16,
        help="Number of concurrent worker threads (default: 16)",
    )
    parser.add_argument(
        "--scales",
        type=str,
        default="1000,10000,100000",
        help="Comma-separated pre-seeded row counts",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON report file path",
    )
    args = parser.parse_args()

    scales = [int(s.strip()) for s in args.scales.split(",") if s.strip()]
    out_path = Path(args.output) if args.output else ARTIFACTS_DIR / "load_test_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Hardware & Environment Metadata
    hardware = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "processor": platform.processor() or "unknown",
        "cpu_count_logical": os.cpu_count() or 1,
    }

    scale_results: list[dict[str, Any]] = []

    for scale in scales:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        port = _find_free_port()
        os.environ["CHARGEBACK_ENV"] = "production"
        os.environ["CHARGEBACK_API_KEY"] = API_KEY
        os.environ["CHARGEBACK_API_KEYS"] = f"client-1:{API_KEY}:write"
        os.environ["CHARGEBACK_RATE_LIMIT"] = "100000"
        os.environ["CHARGEBACK_DB_PATH"] = db_path
        os.environ["CHARGEBACK_AUDIT_DB_PATH"] = db_path

        import uvicorn

        from chargeback_risk_engine.api import app
        from chargeback_risk_engine.settings import reset_settings

        reset_settings()

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        # Wait for server readiness
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1.0) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.1)

        try:
            res = benchmark_scale(
                n_rows=scale,
                concurrency=args.concurrency,
                duration=args.duration,
                port=port,
                db_path=db_path,
            )
            scale_results.append(res)
        finally:
            server.should_exit = True
            server_thread.join(timeout=3.0)
            try:
                os.remove(db_path)
            except OSError:
                pass

    # Verify sub-linear graph scaling
    scale_1k = next((r for r in scale_results if r["pre_seeded_rows"] == 1000), None)
    scale_100k = next((r for r in scale_results if r["pre_seeded_rows"] == 100000), None)
    scaling_ratio_p95 = (
        round(scale_100k["latency_p95_ms"] / max(0.1, scale_1k["latency_p95_ms"]), 2)
        if scale_1k and scale_100k
        else None
    )

    report = {
        "suite": "production_asgi_load_test",
        "description": "Measured latency and throughput across pre-seeded database scales with auth, audit hashing, and provenance verification",
        "hardware": hardware,
        "concurrency": args.concurrency,
        "configured_duration_seconds_per_scale": args.duration,
        "scaling_ratio_p95_100k_vs_1k": scaling_ratio_p95,
        "sublinear_scaling_verified": bool(scaling_ratio_p95 and scaling_ratio_p95 <= 2.5),
        "results": scale_results,
    }

    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[LoadTest] Wrote load test report to: {out_path}")


if __name__ == "__main__":
    main()
