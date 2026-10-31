"""scripts/load_test.py — Concurrent load testing and latency measurement harness."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import statistics
import time
from typing import Any

os.environ.setdefault("CHARGEBACK_ENV", "development")
os.environ.setdefault("CHARGEBACK_API_KEY", "dev-test-key-at-least-32-chars-long")

from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app
from chargeback_risk_engine.settings import reset_settings

reset_settings()

API_KEY = "dev-test-key-at-least-32-chars-long"


def run_single_request(client: TestClient, dispute_id: str) -> tuple[bool, float, int]:
    payload: dict[str, Any] = {
        "dispute_id": dispute_id,
        "payment_id": f"pay_{dispute_id}",
        "reason_code": "item_not_received",
        "amount": 4200.0,
        "customer_id": f"cust_{dispute_id}",
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
    t0 = time.perf_counter()
    resp = client.post(
        "/decision",
        json=payload,
        headers={"X-API-Key": API_KEY},
    )
    elapsed = (time.perf_counter() - t0) * 1000.0  # ms
    return (resp.status_code == 200, elapsed, resp.status_code)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chargeback Risk Engine Load Test Harness")
    parser.add_argument("--num-requests", type=int, default=200, help="Total requests to dispatch")
    parser.add_argument("--concurrency", type=int, default=8, help="Number of concurrent workers")
    args = parser.parse_args()

    client = TestClient(app)
    # Warmup
    for i in range(5):
        run_single_request(client, f"warmup_{i}")

    print(
        f"Executing load test: {args.num_requests} requests with concurrency={args.concurrency}..."
    )
    latencies: list[float] = []
    successes = 0

    start_wall = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(run_single_request, client, f"load_test_req_{i}")
            for i in range(args.num_requests)
        ]
        for f in concurrent.futures.as_completed(futures):
            ok, lat, code = f.result()
            if ok:
                successes += 1
            latencies.append(lat)

    total_wall = time.perf_counter() - start_wall
    rps = args.num_requests / total_wall if total_wall > 0 else 0

    sorted_lats = sorted(latencies)
    p50 = statistics.median(sorted_lats)
    p95 = sorted_lats[int(0.95 * len(sorted_lats))]
    p99 = sorted_lats[int(0.99 * len(sorted_lats))]
    mean_lat = statistics.mean(sorted_lats)

    print("\n--- Load Test Results ---")
    print(f"Total Requests:     {args.num_requests}")
    print(
        f"Success Rate:       {successes / args.num_requests * 100:.1f}% ({successes}/{args.num_requests})"
    )
    print(f"Total Wall Time:    {total_wall:.2f} s")
    print(f"Throughput:         {rps:.1f} req/s")
    print(f"Mean Latency:       {mean_lat:.2f} ms")
    print(f"P50 Latency:        {p50:.2f} ms")
    print(f"P95 Latency:        {p95:.2f} ms")
    print(f"P99 Latency:        {p99:.2f} ms")


if __name__ == "__main__":
    main()
