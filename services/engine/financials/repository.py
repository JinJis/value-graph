"""Per-company financials persistence: Protocol + in-memory (tests) + Postgres.

One row per company (``company_financials``), keyed by ticker. ``financials_map`` feeds
the CVE pipeline's ``financials`` input (the complementary side of each trade).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from services.engine.db.config import DbSettings
from services.engine.financials.models import (
    FinancialsRecord,
    FinancialsUpsert,
    to_buckets,
)


class FinancialsRepository(Protocol):
    def upsert(self, data: FinancialsUpsert) -> FinancialsRecord: ...

    def get(self, company_ticker: str) -> FinancialsRecord | None: ...

    def list_for(self, tickers: list[str] | None = None) -> list[FinancialsRecord]: ...


class InMemoryFinancialsRepository:
    def __init__(self) -> None:
        self._by_ticker: dict[str, FinancialsRecord] = {}

    def upsert(self, data: FinancialsUpsert) -> FinancialsRecord:
        existing = self._by_ticker.get(data.company_ticker)
        record = FinancialsRecord(
            id=existing.id if existing else str(uuid4()),
            updated_at=datetime.now(UTC),
            **data.model_dump(),
        )
        self._by_ticker[data.company_ticker] = record
        return record

    def get(self, company_ticker: str) -> FinancialsRecord | None:
        return self._by_ticker.get(company_ticker)

    def list_for(self, tickers: list[str] | None = None) -> list[FinancialsRecord]:
        items = list(self._by_ticker.values())
        if tickers is not None:
            wanted = set(tickers)
            items = [r for r in items if r.company_ticker in wanted]
        return sorted(items, key=lambda r: r.company_ticker)


def financials_map(
    repo: FinancialsRepository, tickers: list[str]
) -> dict[str, dict[str, float]]:
    """Build the ``{ticker -> {bucket -> value}}`` map the CVE pipeline consumes."""
    out: dict[str, dict[str, float]] = {}
    for record in repo.list_for(tickers):
        buckets = to_buckets(record)
        if buckets:
            out[record.company_ticker] = buckets
    return out


_COLS = (
    "id, company_ticker, revenue, cogs, capex, rnd, sga, currency, as_of_date, "
    "source, updated_at"
)


def _row_to_record(row: dict[str, Any]) -> FinancialsRecord:
    return FinancialsRecord(
        id=str(row["id"]),
        company_ticker=row["company_ticker"],
        revenue=row["revenue"],
        cogs=row["cogs"],
        capex=row["capex"],
        rnd=row["rnd"],
        sga=row["sga"],
        currency=row["currency"],
        as_of_date=row["as_of_date"],
        source=row["source"],
        updated_at=row["updated_at"],
    )


class PostgresFinancialsRepository:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def upsert(self, data: FinancialsUpsert) -> FinancialsRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO company_financials "
                "(company_ticker, revenue, cogs, capex, rnd, sga, currency, as_of_date, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (company_ticker) DO UPDATE SET "
                "revenue = EXCLUDED.revenue, cogs = EXCLUDED.cogs, capex = EXCLUDED.capex, "
                "rnd = EXCLUDED.rnd, sga = EXCLUDED.sga, currency = EXCLUDED.currency, "
                "as_of_date = EXCLUDED.as_of_date, source = EXCLUDED.source, updated_at = now() "
                f"RETURNING {_COLS}",
                (
                    data.company_ticker,
                    data.revenue,
                    data.cogs,
                    data.capex,
                    data.rnd,
                    data.sga,
                    data.currency,
                    data.as_of_date,
                    data.source,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_record(row)

    def get(self, company_ticker: str) -> FinancialsRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM company_financials WHERE company_ticker = %s",
                (company_ticker,),
            )
            row = cur.fetchone()
            return _row_to_record(row) if row is not None else None

    def list_for(self, tickers: list[str] | None = None) -> list[FinancialsRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            if tickers is None:
                cur.execute(f"SELECT {_COLS} FROM company_financials ORDER BY company_ticker")
            else:
                cur.execute(
                    f"SELECT {_COLS} FROM company_financials "
                    "WHERE company_ticker = ANY(%s) ORDER BY company_ticker",
                    (tickers,),
                )
            return [_row_to_record(row) for row in cur.fetchall()]
