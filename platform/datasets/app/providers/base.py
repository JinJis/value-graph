"""Provider Protocols — the contract every market adapter implements.

A provider is responsible for one domain in one market. It fetches from an
upstream source and returns spec-shaped models (``app.models.generated``). The
router never talks to an upstream directly; it resolves a provider from the
registry and calls these methods, so US and KR return identical JSON.

Not every provider implements every domain — the registry only wires the ones
that exist, and unbuilt endpoints raise 501 at the router.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from app.models.generated import (
    BalanceSheet,
    CashFlowStatement,
    CompanyFacts,
    CompanySearchResult,
    EarningsRecord,
    Filing,
    FinancialMetricSnapshot,
    IncomeStatement,
    InsiderTrade,
    InstitutionalHolding,
    InterestRate,
    News,
    Price,
    PriceSnapshot,
)
from app.symbols import Market, SecurityRef


@runtime_checkable
class CompanyProvider(Protocol):
    async def company_facts(self, ref: SecurityRef) -> CompanyFacts: ...
    async def list_tickers(self) -> list[str]: ...
    async def list_ciks(self) -> list[str]: ...
    async def search_companies(
        self, query: str, limit: int
    ) -> list[CompanySearchResult]: ...


@runtime_checkable
class PricesProvider(Protocol):
    async def prices(
        self, ref: SecurityRef, interval: str, start: date, end: date
    ) -> list[Price]: ...
    async def snapshot(self, ref: SecurityRef) -> PriceSnapshot: ...


@runtime_checkable
class FinancialsProvider(Protocol):
    async def income_statements(
        self, ref: SecurityRef, period: str, limit: int
    ) -> list[IncomeStatement]: ...
    async def balance_sheets(
        self, ref: SecurityRef, period: str, limit: int
    ) -> list[BalanceSheet]: ...
    async def cash_flow_statements(
        self, ref: SecurityRef, period: str, limit: int
    ) -> list[CashFlowStatement]: ...


@runtime_checkable
class FilingsProvider(Protocol):
    async def filings(
        self, ref: SecurityRef, filing_types: list[str] | None, limit: int
    ) -> list[Filing]: ...


@runtime_checkable
class MacroProvider(Protocol):
    def banks(self) -> list[dict]: ...
    async def interest_rates(
        self, bank: str, start: date | None, end: date | None
    ) -> list[InterestRate]: ...
    async def snapshot(self, bank: str) -> list[InterestRate]: ...


@runtime_checkable
class MetricsProvider(Protocol):
    async def metrics_snapshot(self, ref: SecurityRef) -> FinancialMetricSnapshot: ...


@runtime_checkable
class NewsProvider(Protocol):
    async def news(self, market: Market, ticker: str | None, limit: int) -> list[News]: ...


@runtime_checkable
class EarningsProvider(Protocol):
    async def earnings(self, ref: SecurityRef, limit: int) -> list[EarningsRecord]: ...


@runtime_checkable
class InsiderProvider(Protocol):
    async def insider_trades(self, ref: SecurityRef, limit: int) -> list[InsiderTrade]: ...


@runtime_checkable
class InstitutionalProvider(Protocol):
    async def by_filer(self, filer_cik: str, limit: int) -> list[InstitutionalHolding]: ...
    async def by_ticker(self, ref: SecurityRef, limit: int) -> list[InstitutionalHolding]: ...
