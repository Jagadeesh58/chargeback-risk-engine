"""Local end-to-end latency benchmark for the canonical decision path across database scales."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chargeback_risk_engine.audit_log import _get_connection
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case


def _populate_scale(db_path: str, count: int) -> None:
    if count <= 0:
        return
    conn = _get_connection(db_path)
    decisions = []
    entities = []
    now = "2026-01-01T00:00:00Z"
    for i in range(count):
        d_id = f"POP_{count}_{i}"
        cust = f"cust_{i % (max(1, count // 2))}"
        ip = f"10.{(i // 256) % 256}.{i % 256}"
        dev = f"dev_{i % (max(1, count // 3))}"
        card = f"card_{i % (max(1, count // 2))}"
        g_data = {"customer_id": cust, "ip_address": ip, "device_id": dev, "card_fingerprint": card}
        g_json = json.dumps(g_data)
        amt = 2500.0
        decisions.append(
            (
                d_id,
                "item_not_received",
                amt,
                0.75,
                "AUTO-CONTEST",
                "prepopulated",
                1500.0,
                "[]",
                now,
                "rules-v1",
                "features-v1",
                "policy-v1",
                g_json,
                "{}",
                "",
                None,
                "",
                "",
                "",
            )
        )
        entities.append((d_id, "customer_id", cust, amt))
        entities.append((d_id, "ip_address", ip, amt))
        entities.append((d_id, "device_id", dev, amt))
        entities.append((d_id, "card_fingerprint", card, amt))
    conn.executemany(
        "INSERT INTO decisions (dispute_id, reason_code, amount, win_probability, action, reason, expected_value, evidence_json, created_at, model_version, feature_version, policy_version, graph_data_json, ai_metadata_json, request_id, routing_score, prev_hash, record_hash, payload_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        decisions,
    )
    conn.executemany(
        "INSERT INTO graph_entities (dispute_id, entity_type, entity_value, amount) VALUES (?, ?, ?, ?)",
        entities,
    )
    conn.commit()
    conn.close()


def benchmark_scale(db_path: str, scale_name: str, runs: int = 100) -> dict:
    case = {
        "dispute_id": "LATENCY_TEMPLATE",
        "payment_id": "pay_latency",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "customer_id": "cust_bench_target",
        "ip_address": "10.0.0.1",
        "device_id": "dev_bench_target",
        "card_fingerprint": "card_bench_target",
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    # Warmup
    decide_case(
        {**case, "dispute_id": f"warmup_{scale_name}"},
        db_path=db_path,
        include_counterfactual=False,
    )
    samples = []
    for i in range(runs):
        start = time.perf_counter_ns()
        decide_case(
            {**case, "dispute_id": f"LAT_{scale_name}_{i}"},
            db_path=db_path,
            include_counterfactual=False,
        )
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    samples.sort()

    def pct(p: float) -> float:
        return round(samples[min(len(samples) - 1, max(0, int((p / 100) * len(samples)) - 1))], 2)

    return {
        "scale": scale_name,
        "runs": runs,
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "max_ms": round(max(samples), 2),
    }


def main():
    scales = [
        ("empty", 0, 50),
        ("100_rows", 100, 50),
        ("1k_rows", 1_000, 50),
        ("10k_rows", 10_000, 50),
        ("50k_rows", 50_000, 25),
    ]
    results = []
    print("Running end-to-end decision latency benchmarks across database scales...", flush=True)
    with tempfile.TemporaryDirectory(prefix="latency_bench_") as tmp:
        for name, count, runs in scales:
            db = str(Path(tmp) / f"audit_{name}.db")
            if count > 0:
                _populate_scale(db, count)
            res = benchmark_scale(db, name, runs=runs)
            results.append(res)
            print(
                f"[{name}] (n={runs}): p50={res['p50_ms']}ms, p95={res['p95_ms']}ms, p99={res['p99_ms']}ms",
                flush=True,
            )

    res_10k = next((r for r in results if r["scale"] == "10k_rows"), results[-1])
    print("\nSummary Result:", flush=True)
    summary = {
        "label": "LOCAL END-TO-END DECISION LATENCY",
        "benchmark_by_scale": results,
        "headline_10k": res_10k,
        "p50_ms": res_10k["p50_ms"],
        "p95_ms": res_10k["p95_ms"],
        "p99_ms": res_10k["p99_ms"],
        "max_ms": res_10k["max_ms"],
        "method": "warm model artifacts; unique dispute_id per timed request; indexed 2-hop subgraph query; local process and filesystem",
    }
    print(json.dumps(summary, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    main()
