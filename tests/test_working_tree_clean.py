"""Test that test execution leaves the git working tree clean of tracked modifications."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tracked_files_unmodified_by_tests():
    """Verify that git status shows no modified tracked files after test execution."""
    if not (REPO_ROOT / ".git").exists() or not shutil.which("git"):
        pytest.skip("Not running inside a git repository checkout")

    result = subprocess.run(
        ["git", "status", "--porcelain", "-uno"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git status failed: {result.stderr}"
    modified = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    # Protect against any test modifying artifacts/, docs/, data/ in-place
    dirtied_protected_dirs = [
        line for line in modified if any(d in line for d in ("artifacts/", "docs/", "data/"))
    ]
    assert not dirtied_protected_dirs, (
        f"Protected artifacts/docs/data modified during tests: {dirtied_protected_dirs}. "
        "Tests must not modify repository artifacts, documentation, or data in place."
    )

    # In CI or clean clone, absolutely no tracked file should be modified
    if os.environ.get("CI"):
        assert not modified, f"Tracked files modified during tests in CI: {modified}."
