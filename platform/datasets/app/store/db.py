"""Ingestion store engine + session.

SQLite by default (zero-setup for dev); set ``DATABASE_URL`` to a ``postgresql://``
URL in production. The same schema serves both — this is the store that backs the
screener / line-items search and (later) bulk historical backfill.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    from app.store import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(engine)
