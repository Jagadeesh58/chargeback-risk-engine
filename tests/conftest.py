import os
from pathlib import Path
import pytest
from chargeback_risk_engine.audit_log import DB_PATH

# Default to development mode for test suite unless a test explicitly overrides it
os.environ.setdefault("CHARGEBACK_ENV", "development")
os.environ.setdefault("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True, scope="session")
def cleanup_root_test_artifacts():
    yield
    # Clean up any test database or model files left in repo root
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except OSError:
            pass
    for stray in (
        "test_ml_scorer_model_pytest.pkl",
        "test_ml_scorer_model_pytest.pkl.sha256",
    ):
        stray_path = REPO_ROOT / stray
        if stray_path.exists():
            try:
                os.remove(stray_path)
            except OSError:
                pass
