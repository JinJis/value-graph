"""[M6-FEED-04] Feed persistence: Protocol + in-memory (tests) + Postgres.

Items are returned newest-first (recency only — no scoring/ranking). ``entity``
filters to items linked to a ticker, which is how node-select narrows the feed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.engine.db.config import DbSettings
from services.pipeline.feed.models import FeedItem, FeedItemCreate


class FeedRepository(Protocol):
    def add_item(self, theme_id: str, data: FeedItemCreate) -> FeedItem: ...

    def list_items(
        self, theme_id: str, *, entity: str | None = None, limit: int = 50
    ) -> list[FeedItem]: ...


class InMemoryFeedRepository:
    def __init__(self) -> None:
        self._items: list[FeedItem] = []

    def add_item(self, theme_id: str, data: FeedItemCreate) -> FeedItem:
        item = FeedItem(
            id=str(uuid4()),
            theme_id=theme_id,
            created_at=datetime.now(UTC),
            **data.model_dump(),
        )
        self._items.append(item)
        return item

    def list_items(
        self, theme_id: str, *, entity: str | None = None, limit: int = 50
    ) -> list[FeedItem]:
        items = [i for i in self._items if i.theme_id == theme_id]
        if entity is not None:
            items = [i for i in items if entity in i.entities]
        items.sort(key=lambda i: i.published_at, reverse=True)  # newest first, no scoring
        return items[:limit]


def _row_to_item(row: dict[str, Any]) -> FeedItem:
    return FeedItem(
        id=str(row["id"]),
        theme_id=str(row["theme_id"]),
        title=row["title"],
        url=row["url"],
        source_type=row["source_type"],
        publisher=row["publisher"],
        published_at=row["published_at"],
        snippet=row["snippet"],
        entities=row["entities"] or [],
        created_at=row["created_at"],
    )


_COLS = (
    "id, theme_id, title, url, source_type, publisher, published_at, snippet, "
    "entities, created_at"
)


class PostgresFeedRepository:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def add_item(self, theme_id: str, data: FeedItemCreate) -> FeedItem:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feed_items "
                "(theme_id, title, url, source_type, publisher, published_at, snippet, entities) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLS}",
                (
                    theme_id,
                    data.title,
                    data.url,
                    data.source_type,
                    data.publisher,
                    data.published_at,
                    data.snippet,
                    Jsonb(data.entities),
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_item(row)

    def list_items(
        self, theme_id: str, *, entity: str | None = None, limit: int = 50
    ) -> list[FeedItem]:
        clauses = ["theme_id = %s"]
        params: list[Any] = [theme_id]
        if entity is not None:
            clauses.append("entities ? %s")  # jsonb array contains the ticker
            params.append(entity)
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM feed_items WHERE {' AND '.join(clauses)} "
                "ORDER BY published_at DESC LIMIT %s",
                tuple(params),
            )
            return [_row_to_item(row) for row in cur.fetchall()]
