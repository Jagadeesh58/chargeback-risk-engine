"""Thin entry point for ``uvicorn apps.api:app``.

The canonical FastAPI implementation lives in ``chargeback_risk_engine.api``.
This module re-exports that single application.
"""

from chargeback_risk_engine.api import app

__all__ = ["app"]
