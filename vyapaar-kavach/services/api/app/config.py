"""Central configuration for the Vyapaar Kavach demo API.

All settings come from environment variables (see `.env.example`).
Nothing here contains secrets: the synthetic demo needs no real credentials.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root = vyapaar-kavach/ (three levels above this file).
REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(key: str, default: str) -> str:
    value = os.environ.get(key)
    return value if value not in (None, "") else default


class Settings:
    """Runtime settings, resolved once at import time."""

    # --- database ---------------------------------------------------------
    # Default is a local SQLite file so the demo runs with zero services.
    # Switch to Postgres with: see compose.yaml + README.
    DATABASE_URL: str = _env("DATABASE_URL", f"sqlite:///{REPO_ROOT / 'vyapaar.db'}")

    # --- application mode ---------------------------------------------------
    # This prototype build intentionally supports ONLY the synthetic demo mode.
    APP_ENVIRONMENT: str = _env("APP_ENVIRONMENT", "DEMO_LOCAL")

    # --- seeded demo credentials (local demonstration accounts only) --------
    DEMO_OWNER_PASSWORD: str = _env("DEMO_OWNER_PASSWORD", "owner123")
    DEMO_STAFF_PASSWORD: str = _env("DEMO_STAFF_PASSWORD", "staff123")
    DEMO_RESEARCHER_PASSWORD: str = _env("DEMO_RESEARCHER_PASSWORD", "research123")

    # --- ML assets (original-domain GATv2 engine) ---------------------------
    # Defaults point at the checkpoint/dataset sitting next to this folder.
    ML_DATASET_PATH: Path = Path(_env("ML_DATASET_PATH", "../dataset1 (1).pt"))
    ML_CHECKPOINT_PATH: Path = Path(_env("ML_CHECKPOINT_PATH", "../GAT_Model_Final (2).pt"))
    ML_ARTIFACTS_DIR: Path = REPO_ROOT / _env("ML_ARTIFACTS_DIR", "ml/artifacts")

    # --- evidence exports ----------------------------------------------------
    EXPORTS_DIR: Path = REPO_ROOT / _env("EXPORTS_DIR", "services/api/artifacts/exports")

    # --- sessions -------------------------------------------------------------
    SESSION_COOKIE: str = "vk_session"
    SESSION_TTL_HOURS: int = 12
    SESSION_SECURE: bool = _env("SESSION_SECURE", "false").lower() == "true"

    def resolved(self, p: Path) -> Path:
        """Resolve possibly-relative artifact paths against the repo root."""
        return p if p.is_absolute() else (REPO_ROOT / p)


settings = Settings()
