"""Test that Prometheus alert rule definitions reference real metrics produced by the engine."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from chargeback_risk_engine.api import app

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = REPO_ROOT / "deploy"


def _extract_metric_names_from_alert_file(file_path: Path) -> set[str]:
    content = file_path.read_text(encoding="utf-8")
    expr_lines = [
        line.split("expr:", 1)[1].strip() for line in content.splitlines() if "expr:" in line
    ]
    metric_names = set()
    for expr in expr_lines:
        # Match metric identifier patterns like chargeback_xxx_total or chargeback_xxx_seconds_bucket
        found = re.findall(r"\b(chargeback_[a-zA-Z0-9_]+)\b", expr)
        for m in found:
            # Strip Prometheus histogram/summary suffixes for matching base metric
            base_m = re.sub(r"_(bucket|sum|count)$", "", m)
            metric_names.add(base_m)
    return metric_names


def test_alert_rule_metrics_exist_in_observability():
    """Verify that all alert rules reference metrics that actually exist in /metrics output."""
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200, f"/metrics endpoint failed with code {resp.status_code}"
    metrics_text = resp.text

    alert_files = [
        DEPLOY_DIR / "alert_rules.yml",
        DEPLOY_DIR / "prometheus-alerts.yaml",
    ]

    for alert_file in alert_files:
        assert alert_file.exists(), f"Alert rules file missing: {alert_file}"
        referenced = _extract_metric_names_from_alert_file(alert_file)
        assert referenced, f"No chargeback metrics extracted from {alert_file}"

        missing = []
        for metric in referenced:
            if metric not in metrics_text:
                missing.append(metric)

        assert not missing, (
            f"Alert file '{alert_file.name}' references metrics not found in /metrics: {missing}"
        )
