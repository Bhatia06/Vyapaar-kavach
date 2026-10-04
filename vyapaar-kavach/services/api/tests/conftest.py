"""Test configuration: isolated temp SQLite DB + seeded world per test.

Environment variables must be set BEFORE importing the app modules because
settings are resolved at import time.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_TMP = Path(os.environ.get("VK_TEST_TMP", "")) or None

# Resolve isolation paths up-front (before app imports happen at fixture time).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEST_DIR = _REPO_ROOT / ".test_artifacts"
_TEST_DIR.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR / 'test.db'}"
os.environ["EXPORTS_DIR"] = str(_TEST_DIR / "exports")

from fastapi.testclient import TestClient  # noqa: E402

from services.api.app.db import SessionLocal, create_all  # noqa: E402
from services.api.app.main import app  # noqa: E402
from services.api.fixtures.seed import reset, seed  # noqa: E402

create_all()


def _fresh_client() -> TestClient:
    """A fresh client against the current world (does NOT reseed)."""
    return TestClient(app)


@pytest.fixture()
def world():
    """Reset + reseed exactly once per test. Role fixtures depend on this so
    their sessions survive each other (re-seeding would wipe session rows)."""
    db = SessionLocal()
    try:
        reset(db)
        seed(db)
    finally:
        db.close()
    yield


@pytest.fixture()
def client(world):
    c = _fresh_client()
    yield c
    c.close()


def _login(c: TestClient, username: str, password: str) -> TestClient:
    r = c.post("/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def _role_client(world, username: str, password: str) -> TestClient:
    """Independent client per role — a second login on a shared TestClient
    would overwrite the session cookie and silently change identity."""
    c = _fresh_client()
    return _login(c, username, password)


@pytest.fixture()
def owner_client(world):
    c = _role_client(world, "owner@demo", "owner123")
    yield c
    c.close()


@pytest.fixture()
def staff_client(world):
    c = _role_client(world, "staff@demo", "staff123")
    yield c
    c.close()


@pytest.fixture()
def research_client(world):
    c = _role_client(world, "research@demo", "research123")
    yield c
    c.close()


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
