"""ORM models for the ingestion store.

``FinancialFact`` is point-in-time / restatement-aware: the same (ticker, line
item, period, report_period) can exist under different ``accession_number``s, so
an originally-reported value and a later restatement are both retained rather
than overwritten (CLAUDE.md: reconcile, don't overwrite). ``accession_number``
is stored as "" (not NULL) when absent so the uniqueness constraint holds.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.store.db import Base


class FinancialFact(Base):
    __tablename__ = "financial_facts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(2), index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    cik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    statement: Mapped[str] = mapped_column(String(16))  # income | balance | cashflow
    line_item: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    period: Mapped[str] = mapped_column(String(10))  # annual | quarterly | ttm
    report_period: Mapped[date] = mapped_column(index=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    filing_date: Mapped[date | None] = mapped_column(nullable=True)
    accession_number: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(24))
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "market", "ticker", "statement", "line_item", "period", "report_period",
            "accession_number", name="uq_financial_fact",
        ),
        Index("ix_fact_screen", "line_item", "period", "report_period"),
        Index("ix_fact_lookup", "market", "ticker", "line_item", "period"),
    )


class FactLocation(Base):
    """PH-PROV2: where a financial fact LITERALLY appears in its source filing.

    A precomputed pointer from the deterministic match key the agent already holds
    (market, cik, accession, concept, report_period) to the exact inline-XBRL element
    in the primary document. The highlighted evidence image is rendered lazily from
    this pointer at query time — never fabricated. ``status`` records matched / miss /
    unavailable so a gap degrades gracefully (no image) instead of guessing."""

    __tablename__ = "fact_locations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(2), index=True)
    cik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    accession_number: Mapped[str] = mapped_column(String(40), index=True)
    concept: Mapped[str] = mapped_column(String(96))       # bare us-gaap concept
    period: Mapped[str] = mapped_column(String(10))        # annual | quarterly
    report_period: Mapped[date] = mapped_column(index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    primary_doc_url: Mapped[str] = mapped_column(Text)
    element_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    selector: Mapped[str | None] = mapped_column(Text, nullable=True)   # XPath fallback
    scale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sign: Mapped[str | None] = mapped_column(String(2), nullable=True)
    match_rule: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # matched | miss | unavailable
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "market", "cik", "accession_number", "concept", "report_period",
            name="uq_fact_location",
        ),
        Index("ix_factloc_lookup", "market", "accession_number", "concept", "report_period"),
    )


class IngestionJob(Base):
    """One ingestion run (manual backfill or a scheduled refresh) — so operators can
    see what was loaded, when, how many rows, and any error, instead of guessing
    why the store is empty. Surfaced in the admin ops console (PH-1)."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # backfill | scheduled
    market: Mapped[str | None] = mapped_column(String(2), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(256), nullable=True)  # tickers / universe / "deep"
    status: Mapped[str] = mapped_column(String(12), index=True)  # running | success | error
    rows: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)  # tickers to process
    done: Mapped[int] = mapped_column(Integer, default=0)   # tickers processed (live progress)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Company(Base):
    __tablename__ = "companies"

    market: Mapped[str] = mapped_column(String(2), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
