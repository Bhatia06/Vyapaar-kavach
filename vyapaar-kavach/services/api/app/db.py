"""Database engine/session management.

Kept deliberately small: one module-level engine, a session factory, and a
FastAPI dependency that yields a session per request.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_engine_url = settings.DATABASE_URL

# SQLite needs check_same_thread=False when sharing connections across
# FastAPI worker threads; enable WAL + foreign keys for correct behaviour.
_connect_args = {"check_same_thread": False} if _engine_url.startswith("sqlite") else {}

engine: Engine = create_engine(_engine_url, connect_args=_connect_args, future=True)

if _engine_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def create_all() -> None:
    """Create tables (demo bootstrap; a real deployment would use Alembic)."""
    from . import models  # noqa: F401  (registers metadata)
    models.Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
