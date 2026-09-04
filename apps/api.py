"""Thin entry point for `uvicorn apps.api:app`. All real logic lives in
chargeback_risk_engine/api.py — this file only re-exports it so there is
exactly one implementation, not two copies that can silently drift apart.
"""
from chargeback_risk_engine.api import app