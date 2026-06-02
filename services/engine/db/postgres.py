"""Postgres connection + migration runner (raw SQL under infra/migrations/postgres)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from services.engine.db.config import DbSettings
from services.engine.db.planning import discover, plan, split_statements

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "infra" / "migrations" / "postgres"


def connect(settings: DbSettings) -> psycopg.Connection[Any]:
    return psycopg.connect(settings.database_url)


def _ensure_migrations_table(cur: psycopg.Cursor[Any]) -> None:
    cur.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version text PRIMARY KEY, "
        "applied_at timestamptz NOT NULL DEFAULT now())"
    )


def _applied_versions(cur: psycopg.Cursor[Any]) -> set[str]:
    cur.execute("SELECT version FROM schema_migrations")
    return {str(row[0]) for row in cur.fetchall()}


def apply_migrations(
    conn: psycopg.Connection[Any], directory: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply pending Postgres migrations; return the versions applied this run.

    Idempotent: already-applied versions are skipped, so a second call returns [].
    """
    discovered = discover(directory, "*.sql")
    with conn.cursor() as cur:
        _ensure_migrations_table(cur)
        applied = _applied_versions(cur)
        pending = plan(discovered, applied)
        for migration in pending:
            for statement in split_statements(migration.body):
                cur.execute(statement)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (migration.version,),
            )
    conn.commit()
    return [migration.version for migration in pending]
