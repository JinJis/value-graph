"""Theme/Source persistence: a Protocol with an in-memory impl (tests) and a
Postgres impl (production)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from services.engine.db.config import DbSettings
from services.engine.themes.models import (
    SourceCreate,
    SourceRecord,
    Theme,
    ThemeCreate,
)


class ThemeRepository(Protocol):
    def create_theme(self, data: ThemeCreate) -> Theme: ...

    def list_themes(self) -> list[Theme]: ...

    def get_theme(self, theme_id: str) -> Theme | None: ...

    def add_source(self, theme_id: str, data: SourceCreate) -> SourceRecord: ...

    def list_sources(self, theme_id: str) -> list[SourceRecord]: ...

    def get_source(self, source_id: str) -> SourceRecord | None: ...


class InMemoryThemeRepository:
    """Dict-backed repository for tests (no database)."""

    def __init__(self) -> None:
        self._themes: dict[str, Theme] = {}
        self._sources: dict[str, SourceRecord] = {}

    def create_theme(self, data: ThemeCreate) -> Theme:
        now = datetime.now(UTC)
        theme = Theme(
            id=str(uuid4()),
            name=data.name,
            version=1,
            status="draft",
            description=data.description,
            seed_tickers=list(data.seed_tickers),
            published_at=None,
            created_at=now,
            updated_at=now,
        )
        self._themes[theme.id] = theme
        return theme

    def list_themes(self) -> list[Theme]:
        return sorted(self._themes.values(), key=lambda t: t.created_at, reverse=True)

    def get_theme(self, theme_id: str) -> Theme | None:
        return self._themes.get(theme_id)

    def add_source(self, theme_id: str, data: SourceCreate) -> SourceRecord:
        record = SourceRecord(
            id=str(uuid4()),
            theme_id=theme_id,
            verification_status="unverified",
            created_at=datetime.now(UTC),
            **data.model_dump(),
        )
        self._sources[record.id] = record
        return record

    def list_sources(self, theme_id: str) -> list[SourceRecord]:
        return [s for s in self._sources.values() if s.theme_id == theme_id]

    def get_source(self, source_id: str) -> SourceRecord | None:
        return self._sources.get(source_id)


def _row_to_theme(row: dict[str, Any]) -> Theme:
    return Theme(
        id=str(row["id"]),
        name=row["name"],
        version=row["version"],
        status=row["status"],
        description=row["description"],
        seed_tickers=list(row["seed_tickers"] or []),
        published_at=row["published_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_source(row: dict[str, Any]) -> SourceRecord:
    return SourceRecord(
        id=str(row["id"]),
        theme_id=str(row["theme_id"]),
        type=row["type"],
        publisher=row["publisher"],
        as_of_date=row["as_of_date"],
        language=row["language"],
        url=row["url"],
        storage_key=row["storage_key"],
        original_filename=row["original_filename"],
        content_type=row["content_type"],
        verification_status=row["verification_status"],
        created_at=row["created_at"],
    )

_THEME_COLS = (
    "id, name, version, status, description, seed_tickers, "
    "published_at, created_at, updated_at"
)
_SOURCE_COLS = (
    "id, theme_id, type, url, publisher, as_of_date, language, "
    "verification_status, storage_key, original_filename, content_type, created_at"
)


class PostgresThemeRepository:
    """psycopg-backed repository. Opens a short-lived connection per call."""

    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def create_theme(self, data: ThemeCreate) -> Theme:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO themes_meta (name, description, seed_tickers) "
                f"VALUES (%s, %s, %s) RETURNING {_THEME_COLS}",
                (data.name, data.description, list(data.seed_tickers)),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_theme(row)

    def list_themes(self) -> list[Theme]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_THEME_COLS} FROM themes_meta ORDER BY created_at DESC")
            return [_row_to_theme(row) for row in cur.fetchall()]

    def get_theme(self, theme_id: str) -> Theme | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_THEME_COLS} FROM themes_meta WHERE id = %s", (theme_id,))
            row = cur.fetchone()
            return _row_to_theme(row) if row is not None else None

    def add_source(self, theme_id: str, data: SourceCreate) -> SourceRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sources "
                "(theme_id, type, url, publisher, as_of_date, language, "
                "storage_key, original_filename, content_type) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_SOURCE_COLS}",
                (
                    theme_id,
                    data.type,
                    data.url,
                    data.publisher,
                    data.as_of_date,
                    data.language,
                    data.storage_key,
                    data.original_filename,
                    data.content_type,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_source(row)

    def list_sources(self, theme_id: str) -> list[SourceRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SOURCE_COLS} FROM sources WHERE theme_id = %s ORDER BY created_at",
                (theme_id,),
            )
            return [_row_to_source(row) for row in cur.fetchall()]

    def get_source(self, source_id: str) -> SourceRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_SOURCE_COLS} FROM sources WHERE id = %s", (source_id,))
            row = cur.fetchone()
            return _row_to_source(row) if row is not None else None
