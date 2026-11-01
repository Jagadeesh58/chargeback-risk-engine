"""Evidence-first chargeback decisioning engine."""

from __future__ import annotations

try:
    from importlib.metadata import version

    __version__ = version("chargeback-risk-engine")
except Exception:
    __version__ = "1.0.0"

__all__ = ["__version__"]
