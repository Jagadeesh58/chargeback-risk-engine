"""Typed application settings using pydantic-settings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Literal, NamedTuple

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from chargeback_risk_engine.paths import ARTIFACTS_DIR, REPO_ROOT

logger = logging.getLogger("chargeback_risk_engine")


class KeyInfo(NamedTuple):
    key_id: str
    secret: str
    role: Literal["decision", "readonly"]


class Settings(BaseSettings):
    """Runtime configuration for Chargeback Risk Engine."""

    model_config = SettingsConfigDict(
        env_prefix="CHARGEBACK_",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["production", "development", "demo"] = "production"
    debug: bool = False

    # Authentication
    api_key: str = ""
    api_keys: str = ""

    # Paths & storage
    audit_db_path: str = Field(default_factory=lambda: str(REPO_ROOT / "audit_log.db"))
    db_path: str = ""
    model_path: str = Field(default_factory=lambda: str(ARTIFACTS_DIR / "ml_scorer_model.json"))
    model_sha256: str = ""
    require_model_hash: bool = False

    # Security & Networking
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    rate_limit: int = 60
    max_body_bytes: int = 1_048_576  # 1 MB
    request_timeout_seconds: float = 5.0

    # Policy & Feature flags
    allow_unverified_evidence: bool = False
    max_evidence_age_days: float = 365.0
    allow_test_client_header: bool = False

    @property
    def effective_db_path(self) -> str:
        """Return explicit DB path, preferring DB_PATH if set for backwards compatibility."""
        return self.db_path or self.audit_db_path

    @property
    def cors_origin_list(self) -> List[str]:
        if not self.cors_origins:
            return []
        if isinstance(self.cors_origins, list):
            return self.cors_origins
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def get_parsed_api_keys(self) -> Dict[str, KeyInfo]:
        """Parse configured API keys into a lookup dict keyed by secret."""
        results: Dict[str, KeyInfo] = {}

        raw_keys = self.api_keys.strip()
        if raw_keys:
            # Format: "id1:secret1,id2:secret2:readonly,secret3"
            entries = [e.strip() for e in raw_keys.split(",") if e.strip()]
            for idx, entry in enumerate(entries):
                parts = entry.split(":")
                if len(parts) == 1:
                    key_id = f"key_{idx + 1}"
                    secret = parts[0].strip()
                    role: Literal["decision", "readonly"] = "decision"
                elif len(parts) == 2:
                    key_id = parts[0].strip()
                    secret = parts[1].strip()
                    role = "readonly" if key_id.startswith(("ro_", "readonly_")) else "decision"
                else:
                    key_id = parts[0].strip()
                    secret = parts[1].strip()
                    role_str = parts[2].strip().lower()
                    role = "readonly" if role_str in ("readonly", "ro", "read") else "decision"

                if secret:
                    results[secret] = KeyInfo(key_id=key_id, secret=secret, role=role)

        # Fallback / merge single legacy API_KEY
        single_key = self.api_key.strip()
        if single_key and single_key not in results:
            results[single_key] = KeyInfo(key_id="default", secret=single_key, role="decision")

        return results

    def validate_startup(self) -> None:
        """Enforce strict fail-safe validation at application startup."""
        env = self.env.lower().strip()
        if env not in ("production", "development", "demo"):
            raise RuntimeError(
                f"Invalid CHARGEBACK_ENV '{env}'. Must be one of: production, development, demo."
            )

        parsed_keys = self.get_parsed_api_keys()

        if env == "production":
            if self.debug:
                raise RuntimeError("CHARGEBACK_DEBUG must not be enabled in production")

            # Key requirements in production
            if not parsed_keys:
                raise RuntimeError(
                    "CHARGEBACK_API_KEY must be set in production mode. "
                    "Set CHARGEBACK_ENV=development for local testing."
                )

            # Check for legacy single key length (must be >= 32 chars for backward test compatibility)
            if self.api_key.strip() and len(self.api_key.strip()) < 32:
                raise RuntimeError(
                    "CHARGEBACK_API_KEY must be at least 32 characters in production mode."
                )

            for secret, info in parsed_keys.items():
                if not secret.strip() or len(secret) < 16:
                    raise RuntimeError(
                        f"API key for actor '{info.key_id}' must be at least 16 characters in production mode."
                    )

            # DB path security check
            package_dir = Path(__file__).resolve().parent
            resolved_db = Path(self.effective_db_path).resolve()
            if package_dir in resolved_db.parents or resolved_db == package_dir:
                raise RuntimeError(
                    f"CHARGEBACK_AUDIT_DB_PATH cannot be located inside package directory: {resolved_db}"
                )
            if not Path(self.effective_db_path).is_absolute():
                raise RuntimeError(
                    f"CHARGEBACK_AUDIT_DB_PATH must be an absolute path in production: {self.effective_db_path}"
                )

            # CORS origin validation: no wildcards in production
            for origin in self.cors_origin_list:
                if origin == "*":
                    raise RuntimeError("Wildcard CORS origin '*' is forbidden in production")

            # Model hash verification check in production
            model_file = Path(self.model_path)
            sidecar_file = Path(f"{self.model_path}.sha256")
            has_hash = bool(self.model_sha256) or sidecar_file.exists()
            if not has_hash:
                raise RuntimeError(
                    f"CHARGEBACK_MODEL_SHA256 or sidecar hash file missing for model in production: {model_file}"
                )

            if self.allow_unverified_evidence:
                logger.warning(
                    "SECURITY WARNING: CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE is ignored in production mode. "
                    "Fail-closed provenance is strictly enforced."
                )
        else:
            if not parsed_keys:
                logger.warning(
                    "SECURITY WARNING: CHARGEBACK_API_KEY is not set. API is running in %s mode without authentication.",
                    env,
                )
            if self.allow_unverified_evidence:
                logger.warning(
                    "SECURITY WARNING: CHARGEBACK_ALLOW_UNVERIFIED_EVIDENCE=1 is active in %s mode. "
                    "Evidence provenance verification is relaxed for local testing.",
                    env,
                )


def get_settings() -> Settings:
    """Return an application settings instance reflecting current environment."""
    return Settings()


def reset_settings() -> Settings:
    """Return an application settings instance reflecting current environment."""
    return Settings()
