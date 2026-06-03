"""[M4-PUB-04] Publish — sync a gated Staging graph to Production as a read-only snapshot.

Two-Track hard invariants (CLAUDE.md):
- Publish is an EXPLICIT human action — never auto-publish. ``publish`` requires an
  ``actor`` and a passed :class:`~services.engine.publish.gate.GateReport`; otherwise
  it raises :class:`PublishBlocked`.
- Terminal reads Production ONLY. ``ProductionStore.current`` is that read-only seam.
- Later Staging edits must not leak to Production. A snapshot is a deep copy taken at
  publish time; the next publish writes a NEW immutable version — it never mutates a
  published one.

The data-quality meter (verified/derived/estimated/gap %) is M4-DQ-05.
"""

from __future__ import annotations

import copy
import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from services.engine.db.artifacts import GapEdge
from services.engine.db.config import DbSettings
from services.engine.publish.assemble import AssembledGraph
from services.engine.publish.gate import GateReport

logger = logging.getLogger(__name__)


class PublishBlocked(Exception):
    """Raised when a publish is attempted without a passing gate (no auto/forced publish)."""


class ProductionSnapshot(BaseModel):
    """An immutable, versioned Production snapshot — what Terminal renders."""

    id: str
    theme_id: str
    snapshot_version: int  # Production-side, monotonically increasing
    source_build_version: int  # the Staging build it was published from
    published_by: str
    published_at: datetime
    completeness: float
    companies: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    ghost_edges: list[GapEdge] = Field(default_factory=list)


class ProductionStore(Protocol):
    def next_snapshot_version(self, theme_id: str) -> int: ...

    def save_snapshot(self, snapshot: ProductionSnapshot) -> ProductionSnapshot: ...

    def current(self, theme_id: str) -> ProductionSnapshot | None: ...

    def get(self, theme_id: str, snapshot_version: int) -> ProductionSnapshot | None: ...

    def list_versions(self, theme_id: str) -> list[int]: ...


class InMemoryProductionStore:
    def __init__(self) -> None:
        self._snaps: dict[str, dict[int, ProductionSnapshot]] = {}

    def next_snapshot_version(self, theme_id: str) -> int:
        return max(self._snaps.get(theme_id, {}), default=0) + 1

    def save_snapshot(self, snapshot: ProductionSnapshot) -> ProductionSnapshot:
        stored = snapshot.model_copy(deep=True)
        self._snaps.setdefault(snapshot.theme_id, {})[snapshot.snapshot_version] = stored
        return stored

    def current(self, theme_id: str) -> ProductionSnapshot | None:
        versions = self._snaps.get(theme_id, {})
        return versions[max(versions)].model_copy(deep=True) if versions else None

    def get(self, theme_id: str, snapshot_version: int) -> ProductionSnapshot | None:
        found = self._snaps.get(theme_id, {}).get(snapshot_version)
        return found.model_copy(deep=True) if found is not None else None

    def list_versions(self, theme_id: str) -> list[int]:
        return sorted(self._snaps.get(theme_id, {}))


def _content(snapshot: ProductionSnapshot) -> dict[str, Any]:
    return {
        "completeness": snapshot.completeness,
        "source_build_version": snapshot.source_build_version,
        "companies": snapshot.companies,
        "edges": snapshot.edges,
        "ghost_edges": [g.model_dump() for g in snapshot.ghost_edges],
    }


def _row_to_snapshot(row: dict[str, Any]) -> ProductionSnapshot:
    content = row["content"]
    return ProductionSnapshot(
        id=str(row["id"]),
        theme_id=str(row["theme_id"]),
        snapshot_version=row["snapshot_version"],
        source_build_version=row["source_build_version"],
        published_by=row["published_by"],
        published_at=row["published_at"],
        completeness=content.get("completeness", 0.0),
        companies=content.get("companies", []),
        edges=content.get("edges", []),
        ghost_edges=[GapEdge(**g) for g in content.get("ghost_edges", [])],
    )


_COLS = (
    "id, theme_id, snapshot_version, source_build_version, published_by, content, published_at"
)


class PostgresProductionStore:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def next_snapshot_version(self, theme_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(snapshot_version), 0) + 1 AS v "
                "FROM production_snapshots WHERE theme_id = %s",
                (theme_id,),
            )
            row = cur.fetchone()
            assert row is not None
            return int(row["v"])

    def save_snapshot(self, snapshot: ProductionSnapshot) -> ProductionSnapshot:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO production_snapshots "
                "(theme_id, snapshot_version, source_build_version, published_by, content) "
                f"VALUES (%s, %s, %s, %s, %s) RETURNING {_COLS}",
                (
                    snapshot.theme_id,
                    snapshot.snapshot_version,
                    snapshot.source_build_version,
                    snapshot.published_by,
                    Jsonb(_content(snapshot)),
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_snapshot(row)

    def current(self, theme_id: str) -> ProductionSnapshot | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM production_snapshots WHERE theme_id = %s "
                "ORDER BY snapshot_version DESC LIMIT 1",
                (theme_id,),
            )
            row = cur.fetchone()
            return _row_to_snapshot(row) if row is not None else None

    def get(self, theme_id: str, snapshot_version: int) -> ProductionSnapshot | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM production_snapshots "
                "WHERE theme_id = %s AND snapshot_version = %s",
                (theme_id, snapshot_version),
            )
            row = cur.fetchone()
            return _row_to_snapshot(row) if row is not None else None

    def list_versions(self, theme_id: str) -> list[int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT snapshot_version FROM production_snapshots WHERE theme_id = %s "
                "ORDER BY snapshot_version",
                (theme_id,),
            )
            return [int(row["snapshot_version"]) for row in cur.fetchall()]


def publish(
    assembled: AssembledGraph,
    gate_report: GateReport,
    store: ProductionStore,
    *,
    actor: str,
    published_at: datetime | None = None,
) -> ProductionSnapshot:
    """Publish a gated, assembled graph to Production as the next read-only snapshot.

    Raises :class:`PublishBlocked` unless the graph is assembled and its gate passed —
    publish is an explicit human action, never automatic or forced.
    """
    if not actor or not actor.strip():
        raise PublishBlocked("publish requires an explicit actor")
    if not assembled.assembled:
        raise PublishBlocked("cannot publish a withheld (unassembled) graph")
    if not gate_report.passed:
        raise PublishBlocked("validation gate did not pass; resolve violations or override")
    if gate_report.theme_id != assembled.theme_id or gate_report.version != assembled.version:
        raise PublishBlocked("gate report does not match the assembled graph")

    version = store.next_snapshot_version(assembled.theme_id)
    snapshot = ProductionSnapshot(
        id=str(uuid4()),
        theme_id=assembled.theme_id,
        snapshot_version=version,
        source_build_version=assembled.version,
        published_by=actor,
        published_at=published_at or datetime.now(UTC),
        completeness=assembled.completeness.completeness,
        # Deep copies so later Staging edits never leak into this published snapshot.
        companies=copy.deepcopy(assembled.companies),
        edges=copy.deepcopy(assembled.edges),
        ghost_edges=[g.model_copy(deep=True) for g in assembled.ghost_edges],
    )
    saved = store.save_snapshot(snapshot)
    logger.info(
        "published: theme=%s snapshot_version=%s source_build=%s by=%s edges=%d",
        saved.theme_id,
        saved.snapshot_version,
        saved.source_build_version,
        actor,
        len(saved.edges),
    )
    return saved
