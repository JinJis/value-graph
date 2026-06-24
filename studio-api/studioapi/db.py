"""Studio store engine + session (SQLite default, Postgres via DATABASE_URL)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from studioapi.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _add_missing_columns() -> None:
    """Lightweight forward migration: ADD COLUMN for new fields on existing tables (create_all
    only creates missing TABLES, not columns). Idempotent — skips columns already present. Keeps
    a user's existing SQLite/Postgres data intact across the multi-board upgrade."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    names = inspector.get_table_names()
    if "pinned_artifacts" in names:
        existing = {c["name"] for c in inspector.get_columns("pinned_artifacts")}
        add = {"board_id": "VARCHAR(48)", "x": "INTEGER", "y": "INTEGER", "w": "INTEGER", "h": "INTEGER"}
        with engine.begin() as conn:
            for col, decl in add.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE pinned_artifacts ADD COLUMN {col} {decl}"))
    # F1: onboarding flag on users (default 0 = not yet onboarded)
    if "users" in names:
        ucols = {c["name"] for c in inspector.get_columns("users")}
        if "onboarded" not in ucols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN onboarded BOOLEAN DEFAULT 0"))


def init_db() -> None:
    from studioapi import models  # noqa: F401

    Base.metadata.create_all(engine)
    _add_missing_columns()
