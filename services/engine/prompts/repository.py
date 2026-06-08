"""Persistence for prompt overrides (Postgres + in-memory for tests).

One row per overridden prompt key; absence of a row means "use the registered default".
"""

from __future__ import annotations

from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from services.engine.db.config import DbSettings


class PromptOverrideRepository(Protocol):
    def all(self) -> dict[str, str]: ...

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, text: str) -> None: ...

    def delete(self, key: str) -> None: ...


class InMemoryPromptOverrideRepository:
    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}

    def all(self) -> dict[str, str]:
        return dict(self._by_key)

    def get(self, key: str) -> str | None:
        return self._by_key.get(key)

    def set(self, key: str, text: str) -> None:
        self._by_key[key] = text

    def delete(self, key: str) -> None:
        self._by_key.pop(key, None)


class PostgresPromptOverrideRepository:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def all(self) -> dict[str, str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT key, text FROM prompt_overrides")
            return {row["key"]: row["text"] for row in cur.fetchall()}

    def get(self, key: str) -> str | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT text FROM prompt_overrides WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["text"] if row is not None else None

    def set(self, key: str, text: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO prompt_overrides (key, text) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET text = EXCLUDED.text, updated_at = now()",
                (key, text),
            )

    def delete(self, key: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM prompt_overrides WHERE key = %s", (key,))
