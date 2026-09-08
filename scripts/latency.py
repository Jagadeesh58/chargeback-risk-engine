"""Local end-to-end latency benchmark for the canonical decision path."""
from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chargeback_risk_engine.engine.hybrid_pipeline import decide_case


def main(runs: int = 300):
    case = {
        "dispute_id": "LATENCY_TEMPLATE",
        "payment_id": "pay_latency",
        "reason_code": "item_not_received",
        "amount": 2400.0,
        "has_tracking_number": True,
        "has_delivery_confirmation": True,
        "has_signature_confirmation": True,
    }
    with tempfile.TemporaryDirectory(prefix="latency_") as tmp:
        db = str(Path(tmp) / "audit.db")
        # Warm model artifacts before timing.
        decide_case({**case, "dispute_id": "warmup"}, db_path=db, include_counterfactual=False)
        samples = []
        for i in range(runs):
            start = time.perf_counter_ns()
            decide_case({**case, "dispute_id": f"LATENCY_{i}"}, db_path=db, include_counterfactual=False)
            samples.append((time.perf_counter_ns() - start) / 1_000_000)
    samples.sort()
    pct = lambda p: samples[min(len(samples) - 1, max(0, int((p / 100) * len(samples)) - 1))]
    print({
        "label": "LOCAL END-TO-END DECISION LATENCY",
        "runs": runs,
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "max_ms": max(samples),
        "method": "warm model artifacts; unique dispute_id per timed request; local process and filesystem",
    })


if __name__ == "__main__":
    main()
