"""Ticket persistence: Protocol + in-memory (tests) + Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.engine.db.config import DbSettings
from services.engine.tickets.models import Ticket, TicketCreate


class TicketRepository(Protocol):
    def create_open_ticket(self, theme_id: str, data: TicketCreate) -> Ticket | None: ...

    def list_tickets(self, theme_id: str, status: str | None = None) -> list[Ticket]: ...

    def get_ticket(self, ticket_id: str) -> Ticket | None: ...

    def set_status(self, ticket_id: str, status: str) -> Ticket | None: ...

    def set_resolution(
        self,
        ticket_id: str,
        status: str,
        reason_code: str,
        current_estimate: dict[str, Any] | None = None,
    ) -> Ticket | None: ...

    def list_unresolvable(self, theme_id: str, target: str | None = None) -> list[Ticket]: ...


class InMemoryTicketRepository:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._keys: set[tuple[str, str, str]] = set()  # (theme_id, target, metric)

    def create_open_ticket(self, theme_id: str, data: TicketCreate) -> Ticket | None:
        key = (theme_id, data.target, data.metric)
        if key in self._keys:
            return None
        self._keys.add(key)
        now = datetime.now(UTC)
        ticket = Ticket(
            id=str(uuid4()),
            theme_id=theme_id,
            target=data.target,
            metric=data.metric,
            reason=data.reason,
            status="OPEN",
            reason_code=None,
            current_estimate=data.current_estimate,
            created_at=now,
            updated_at=now,
        )
        self._tickets[ticket.id] = ticket
        return ticket

    def list_tickets(self, theme_id: str, status: str | None = None) -> list[Ticket]:
        items = [t for t in self._tickets.values() if t.theme_id == theme_id]
        if status is not None:
            items = [t for t in items if t.status == status]
        return sorted(items, key=lambda t: t.created_at)

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        return self._tickets.get(ticket_id)

    def set_status(self, ticket_id: str, status: str) -> Ticket | None:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            return None
        updated = ticket.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})
        self._tickets[ticket_id] = updated
        return updated

    def set_resolution(
        self,
        ticket_id: str,
        status: str,
        reason_code: str,
        current_estimate: dict[str, Any] | None = None,
    ) -> Ticket | None:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            return None
        updated = ticket.model_copy(
            update={
                "status": status,
                "reason_code": reason_code,
                "current_estimate": current_estimate,
                "updated_at": datetime.now(UTC),
            }
        )
        self._tickets[ticket_id] = updated
        return updated

    def list_unresolvable(self, theme_id: str, target: str | None = None) -> list[Ticket]:
        items = [
            t
            for t in self._tickets.values()
            if t.theme_id == theme_id and t.status == "UNRESOLVABLE"
        ]
        if target is not None:
            items = [t for t in items if t.target == target]
        return sorted(items, key=lambda t: t.created_at)


_COLS = (
    "id, theme_id, target, metric, reason, status, reason_code, "
    "current_estimate, created_at, updated_at"
)


def _row_to_ticket(row: dict[str, Any]) -> Ticket:
    return Ticket(
        id=str(row["id"]),
        theme_id=str(row["theme_id"]),
        target=row["target"],
        metric=row["metric"],
        reason=row["reason"],
        status=row["status"],
        reason_code=row["reason_code"],
        current_estimate=row["current_estimate"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresTicketRepository:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def create_open_ticket(self, theme_id: str, data: TicketCreate) -> Ticket | None:
        estimate = Jsonb(data.current_estimate) if data.current_estimate is not None else None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tickets (theme_id, target, metric, reason, status, current_estimate) "
                "VALUES (%s, %s, %s, %s, 'OPEN', %s) "
                "ON CONFLICT (theme_id, target, metric) DO NOTHING "
                f"RETURNING {_COLS}",
                (theme_id, data.target, data.metric, data.reason, estimate),
            )
            row = cur.fetchone()
            return _row_to_ticket(row) if row is not None else None

    def list_tickets(self, theme_id: str, status: str | None = None) -> list[Ticket]:
        with self._connect() as conn, conn.cursor() as cur:
            if status is None:
                cur.execute(
                    f"SELECT {_COLS} FROM tickets WHERE theme_id = %s ORDER BY created_at",
                    (theme_id,),
                )
            else:
                cur.execute(
                    f"SELECT {_COLS} FROM tickets WHERE theme_id = %s AND status = %s "
                    "ORDER BY created_at",
                    (theme_id, status),
                )
            return [_row_to_ticket(row) for row in cur.fetchall()]

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM tickets WHERE id = %s", (ticket_id,))
            row = cur.fetchone()
            return _row_to_ticket(row) if row is not None else None

    def set_status(self, ticket_id: str, status: str) -> Ticket | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE tickets SET status = %s, updated_at = now() "
                f"WHERE id = %s RETURNING {_COLS}",
                (status, ticket_id),
            )
            row = cur.fetchone()
            return _row_to_ticket(row) if row is not None else None

    def set_resolution(
        self,
        ticket_id: str,
        status: str,
        reason_code: str,
        current_estimate: dict[str, Any] | None = None,
    ) -> Ticket | None:
        estimate = Jsonb(current_estimate) if current_estimate is not None else None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE tickets SET status = %s, reason_code = %s, current_estimate = %s, "
                f"updated_at = now() WHERE id = %s RETURNING {_COLS}",
                (status, reason_code, estimate, ticket_id),
            )
            row = cur.fetchone()
            return _row_to_ticket(row) if row is not None else None

    def list_unresolvable(self, theme_id: str, target: str | None = None) -> list[Ticket]:
        with self._connect() as conn, conn.cursor() as cur:
            if target is None:
                cur.execute(
                    f"SELECT {_COLS} FROM tickets "
                    "WHERE theme_id = %s AND status = 'UNRESOLVABLE' ORDER BY created_at",
                    (theme_id,),
                )
            else:
                cur.execute(
                    f"SELECT {_COLS} FROM tickets "
                    "WHERE theme_id = %s AND status = 'UNRESOLVABLE' AND target = %s "
                    "ORDER BY created_at",
                    (theme_id, target),
                )
            return [_row_to_ticket(row) for row in cur.fetchall()]
