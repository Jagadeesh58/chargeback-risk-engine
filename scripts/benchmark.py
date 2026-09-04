"""Small reproducible end-to-end latency benchmark (no external service)."""
from pathlib import Path
import sys

# Allow direct execution from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



import statistics
import time

from chargeback_risk_engine.scorer import predict_win_probability
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.policy import decide


def main():
    dispute = {"dispute_id": "BENCH", "reason_code": "item_not_received", "amount": 2400.0, "has_tracking_number": True, "has_delivery_confirmation": True, "has_signature_confirmation": True}
    times = []
    for _ in range(500):
        start = time.perf_counter()
        p = predict_win_probability(dispute)
        packet = assemble(dispute)
        decide(p, dispute["amount"], evidence_packet=packet)
        times.append((time.perf_counter() - start) * 1000)
    print({"runs": len(times), "p50_ms": statistics.median(times), "p95_ms": sorted(times)[int(len(times) * 0.95) - 1], "max_ms": max(times)})


if __name__ == "__main__":
    main()
