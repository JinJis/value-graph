"""Blueprint persistence (Staging): Protocol + in-memory (tests) + Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.engine.blueprint.models import Blueprint, BlueprintRecord, RoundMeta
from services.engine.db.config import DbSettings


class BlueprintRepository(Protocol):
    def next_version(self, theme_id: str) -> int: ...

    def save(
        self, blueprint: Blueprint, round_meta: RoundMeta | None = None
    ) -> BlueprintRecord: ...

    def get_latest(self, theme_id: str) -> BlueprintRecord | None: ...


class InMemoryBlueprintRepository:
    def __init__(self) -> None:
        self._items: list[BlueprintRecord] = []

    def next_version(self, theme_id: str) -> int:
        versions = [b.version for b in self._items if b.theme_id == theme_id]
        return max(versions, default=0) + 1

    def save(
        self, blueprint: Blueprint, round_meta: RoundMeta | None = None
    ) -> BlueprintRecord:
        record = BlueprintRecord(
            id=str(uuid4()),
            created_at=datetime.now(UTC),
            round_meta=round_meta,
            **blueprint.model_dump(),
        )
        self._items.append(record)
        return record

    def get_latest(self, theme_id: str) -> BlueprintRecord | None:
        items = [b for b in self._items if b.theme_id == theme_id]
        return max(items, key=lambda b: b.version, default=None)


def _content_json(blueprint: Blueprint) -> dict[str, Any]:
    return {
        "companies": [c.model_dump() for c in blueprint.companies],
        "relationship_types": blueprint.relationship_types,
        "notes": blueprint.notes,
    }


def _row_to_record(row: dict[str, Any]) -> BlueprintRecord:
    content = row["content"]
    raw_meta = row["round_meta"]
    return BlueprintRecord(
        id=str(row["id"]),
        theme_id=str(row["theme_id"]),
        version=row["version"],
        generated_by=row["generated_by"],
        created_at=row["created_at"],
        round_meta=RoundMeta(**raw_meta) if raw_meta else None,
        companies=content["companies"],
        relationship_types=content.get("relationship_types", []),
        notes=content.get("notes"),
    )


_COLS = "id, theme_id, version, content, generated_by, round_meta, created_at"


class PostgresBlueprintRepository:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def next_version(self, theme_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM blueprints WHERE theme_id = %s",
                (theme_id,),
            )
            row = cur.fetchone()
            assert row is not None
            return int(row["v"])

    def save(
        self, blueprint: Blueprint, round_meta: RoundMeta | None = None
    ) -> BlueprintRecord:
        meta_json = Jsonb(round_meta.model_dump()) if round_meta is not None else None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO blueprints (theme_id, version, content, generated_by, round_meta) "
                f"VALUES (%s, %s, %s, %s, %s) RETURNING {_COLS}",
                (
                    blueprint.theme_id,
                    blueprint.version,
                    Jsonb(_content_json(blueprint)),
                    blueprint.generated_by,
                    meta_json,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_record(row)

    def get_latest(self, theme_id: str) -> BlueprintRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM blueprints WHERE theme_id = %s ORDER BY version DESC LIMIT 1",
                (theme_id,),
            )
            row = cur.fetchone()
            return _row_to_record(row) if row is not None else None
