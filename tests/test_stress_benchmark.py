from pathlib import Path
import json


def test_stress_benchmark_artifact_shape():
    path = Path("artifacts/stress_benchmark.json")
    if path.exists():
        data = json.loads(path.read_text())
        assert data["not_external_data"] is True
        for key in ("baseline", "missingness_25pct", "contradiction_20pct", "amount_shift"):
            assert "precision" in data[key]
            assert "recall" in data[key]
