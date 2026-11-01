import os
import shutil
from pathlib import Path

import pytest

from chargeback_risk_engine.audit_log import DB_PATH

# Default to development mode for test suite unless a test explicitly overrides it
os.environ.setdefault("CHARGEBACK_ENV", "development")
os.environ.setdefault("CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE", "1")
os.environ.setdefault("CHARGEBACK_REQUEST_TIMEOUT_SECONDS", "60.0")

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True, scope="session")
def cleanup_root_test_artifacts():
    initial_modified: set[str] = set()
    git_available = (REPO_ROOT / ".git").exists() and shutil.which("git")
    if git_available:
        import subprocess

        res = subprocess.run(
            ["git", "status", "--porcelain", "-uno"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            initial_modified = set(res.stdout.splitlines())

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

    if git_available:
        import subprocess

        res = subprocess.run(
            ["git", "status", "--porcelain", "-uno"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            final_modified = set(res.stdout.splitlines())
            newly_modified = final_modified - initial_modified
            assert not newly_modified, (
                f"Tracked files modified by test session: {newly_modified}. "
                "Tests must redirect outputs to tmp_path or CHARGEBACK_ARTIFACTS_DIR."
            )
