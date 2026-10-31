# Multi-stage production Dockerfile for Chargeback Risk Engine
# syntax=docker/dockerfile:1

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Production Minimal Runtime
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/appuser/.local/bin:$PATH" \
    CHARGEBACK_ENV=production \
    CHARGEBACK_AUDIT_DB_PATH=/var/lib/chargeback/audit_log.db

# Create non-root user and persistent audit directory
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -m -s /bin/bash appuser && \
    mkdir -p /var/lib/chargeback && \
    chown -R appuser:appuser /var/lib/chargeback /app

# Copy installed Python packages from builder
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy application code and model artifacts
COPY --chown=appuser:appuser chargeback_risk_engine /app/chargeback_risk_engine
COPY --chown=appuser:appuser artifacts /app/artifacts
COPY --chown=appuser:appuser data /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

ENTRYPOINT ["uvicorn", "chargeback_risk_engine.api:app", "--host", "0.0.0.0", "--port", "8000"]
