import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = REPO_ROOT / "chargeback_risk_engine"

LOCAL_MODULES = {"chargeback_risk_engine", "training", "scripts", "tests", "benchmarks"}

# Mapping from import module names to distribution package names in pyproject.toml
IMPORT_TO_DIST = {
    "sklearn": "scikit-learn",
    "prometheus_client": "prometheus-client",
    "pydantic_settings": "pydantic-settings",
}


def _get_pyproject_deps() -> set[str]:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml must exist"
    content = pyproject_path.read_text(encoding="utf-8")

    deps_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
    assert deps_match, "dependencies block must exist in pyproject.toml"

    deps = set()
    for line in deps_match.group(1).splitlines():
        line = line.strip().strip(",").strip('"').strip("'")
        if not line or line.startswith("#"):
            continue
        pkg_name = re.split(r"[><=~!;]", line)[0].strip().lower().replace("_", "-")
        if pkg_name:
            deps.add(pkg_name)
    return deps


def _get_pyproject_all_deps() -> set[str]:
    """All declared dependencies including optional-dependencies."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    deps = _get_pyproject_deps()

    opt_match = re.search(r"\[project\.optional-dependencies\](.*?)(?=\n\[|\Z)", content, re.DOTALL)
    if opt_match:
        for line in opt_match.group(1).splitlines():
            line = line.strip()
            # Skip section headers / assignment lines like "ui = ["
            if (
                not line
                or line.startswith("#")
                or line.endswith("=")
                or line.endswith("[")
                or line == "]"
            ):
                continue
            line = line.strip(",").strip('"').strip("'")
            pkg_name = re.split(r"[><=~!;\[]", line)[0].strip().lower().replace("_", "-")
            if pkg_name:
                deps.add(pkg_name)
    return deps


def _extract_imported_modules(directory: Path) -> set[str]:
    imported = set()
    for py_file in directory.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_name = alias.name.split(".")[0]
                    imported.add(top_name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    top_name = node.module.split(".")[0]
                    imported.add(top_name)
    return imported


def test_core_imports_declared_in_pyproject():
    """All third-party imports in chargeback_risk_engine/ must be declared in pyproject.toml dependencies."""
    stdlib = sys.stdlib_module_names
    core_imports = _extract_imported_modules(PKG_DIR)
    declared_deps = _get_pyproject_deps()

    third_party = {m for m in core_imports if m not in stdlib and m not in LOCAL_MODULES}

    missing = []
    for mod in sorted(third_party):
        dist_name = IMPORT_TO_DIST.get(mod, mod).lower().replace("_", "-")
        if dist_name not in declared_deps:
            missing.append(f"{mod} (expected package: {dist_name})")

    assert not missing, (
        f"Third-party imports in chargeback_risk_engine/ not declared in "
        f"pyproject.toml dependencies: {missing}"
    )


def test_no_forbidden_dependencies_in_core():
    """Non-core dependencies must NOT be imported anywhere in chargeback_risk_engine/."""
    forbidden = {"pytest", "matplotlib", "requests", "httpx"}
    core_imports = _extract_imported_modules(PKG_DIR)
    violation = core_imports & forbidden
    assert not violation, (
        f"Forbidden dependencies imported in chargeback_risk_engine/: {violation}. "
        "Core runtime must remain lightweight and headless."
    )


def test_scripts_and_training_imports_declared():
    """Third-party imports in scripts/ and training/ must be declared in dependencies or optional extras."""
    stdlib = sys.stdlib_module_names
    all_declared = _get_pyproject_all_deps()

    for subdir_name in ("scripts", "training"):
        subdir = REPO_ROOT / subdir_name
        if not subdir.exists():
            continue
        imported = _extract_imported_modules(subdir)
        third_party = {m for m in imported if m not in stdlib and m not in LOCAL_MODULES}
        missing = []
        for mod in sorted(third_party):
            dist_name = IMPORT_TO_DIST.get(mod, mod).lower().replace("_", "-")
            if dist_name not in all_declared:
                missing.append(f"{mod} ({dist_name})")
        assert not missing, (
            f"Third-party imports in {subdir_name}/ not declared anywhere in pyproject.toml: {missing}"
        )


def test_version_single_sourced():
    """Version must agree across pyproject.toml, chargeback_risk_engine, CLI, and API endpoints."""
    from fastapi.testclient import TestClient

    import chargeback_risk_engine
    from chargeback_risk_engine.api import app

    pyproject_path = REPO_ROOT / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    m = re.search(r'version\s*=\s*"([^"]+)"', content)
    assert m, "version must be defined in pyproject.toml"
    expected_version = m.group(1)

    # 1. Package __version__
    assert chargeback_risk_engine.__version__ == expected_version

    # 2. API /healthz
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json().get("version") == expected_version

    # 3. API /health
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json().get("version") == expected_version


def test_py_typed_marker_present():
    """py.typed marker must exist in chargeback_risk_engine/ for PEP 561 compliance."""
    py_typed = PKG_DIR / "py.typed"
    assert py_typed.exists(), "chargeback_risk_engine/py.typed must exist"


def test_sklearn_version_consistency():
    """Assert model artifact's sklearn_version major.minor matches pyproject range and lockfile."""
    import json

    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    model_path = REPO_ROOT / "artifacts" / "ml_scorer_model.json"
    assert model_path.exists(), "artifacts/ml_scorer_model.json must exist"
    model_data = json.loads(model_path.read_text(encoding="utf-8"))
    model_ver = model_data.get("sklearn_version")
    assert model_ver, "sklearn_version must be stamped in model artifact"
    model_mm = ".".join(str(model_ver).split(".")[:2])

    # 1. pyproject.toml check
    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'["\']scikit-learn\s*([><=~!^0-9.,\s]+)["\']', pyproject_text)
    assert m, "scikit-learn specifier must exist in pyproject.toml"
    spec = m.group(1).strip()
    spec_set = SpecifierSet(spec)
    assert Version(model_ver) in spec_set, (
        f"Model sklearn_version {model_ver} is outside pyproject specifier '{spec}'"
    )

    # 2. requirements.lock check
    req_lock = REPO_ROOT / "requirements.lock"
    if req_lock.exists():
        lock_text = req_lock.read_text(encoding="utf-8")
        lock_m = re.search(r"scikit-learn==([0-9.]+)", lock_text)
        assert lock_m, "scikit-learn must be pinned in requirements.lock"
        lock_ver = lock_m.group(1)
        lock_mm = ".".join(lock_ver.split(".")[:2])
        assert model_mm == lock_mm, (
            f"Model sklearn_version major.minor ({model_mm}) does not match requirements.lock ({lock_mm})"
        )

    # 3. requirements-dev.lock check
    dev_lock = REPO_ROOT / "requirements-dev.lock"
    if dev_lock.exists():
        dev_lock_text = dev_lock.read_text(encoding="utf-8")
        dev_m = re.search(r"scikit-learn==([0-9.]+)", dev_lock_text)
        assert dev_m, "scikit-learn must be pinned in requirements-dev.lock"
        dev_lock_ver = dev_m.group(1)
        dev_lock_mm = ".".join(dev_lock_ver.split(".")[:2])
        assert model_mm == dev_lock_mm, (
            f"Model sklearn_version major.minor ({model_mm}) does not match requirements-dev.lock ({dev_lock_mm})"
        )
