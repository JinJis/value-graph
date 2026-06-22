"""Ingestion store engine + session.

SQLite by default (zero-setup for dev); set ``DATABASE_URL`` to a ``postgresql://``
URL in production. The same schema serves both — this is the store that backs the
screener / line-items search and (later) bulk historical backfill.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    if url.startswith("sqlite"):
        # Concurrent pipeline writers were hitting "database is locked". WAL lets readers run
        # alongside the single writer, and a long busy_timeout makes a write WAIT for the lock
        # instead of erroring. `timeout` is the driver-level busy timeout (seconds).
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, future=True)

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _rec):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    from app.store import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(engine)
