"""Observability infrastructure: structured JSON logging and Prometheus metrics."""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import Any

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Context variable for correlating logs with incoming HTTP request IDs
current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_request_id", default="")

# Prometheus metrics
DECISIONS_TOTAL = Counter(
    "chargeback_decisions_total",
    "Total chargeback decisions partitioned by action and reason code",
    ["action", "reason_code"],
)

DECISION_DURATION_SECONDS = Histogram(
    "chargeback_decision_duration_seconds",
    "Latency of decision pipeline execution in seconds",
    ["action"],
    buckets=(0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

EVIDENCE_SCORES = Histogram(
    "chargeback_evidence_scores",
    "Distribution of normalized evidence scores by reason code",
    ["reason_code"],
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

AUDIT_WRITES_TOTAL = Counter(
    "chargeback_audit_writes_total",
    "Total audit log persistence operations partitioned by status (success/replay/conflict/error)",
    ["status"],
)

RATE_LIMIT_EXCEEDED_TOTAL = Counter(
    "chargeback_rate_limit_exceeded_total",
    "Total requests rejected by rate limiting per client key or identifier",
    ["key_id"],
)


class JSONLogFormatter(logging.Formatter):
    """Custom logging formatter outputting standard newline-delimited JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": current_request_id.get(""),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger to use JSON formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid adding multiple duplicate handlers
    has_json_handler = any(isinstance(h.formatter, JSONLogFormatter) for h in root_logger.handlers)
    if not has_json_handler:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONLogFormatter())
        root_logger.addHandler(handler)
