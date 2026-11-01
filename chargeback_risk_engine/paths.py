"""Stable repository paths independent of the current working directory."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("CHARGEBACK_DATA_DIR", str(REPO_ROOT / "data")))
ARTIFACTS_DIR = Path(os.environ.get("CHARGEBACK_ARTIFACTS_DIR", str(REPO_ROOT / "artifacts")))
