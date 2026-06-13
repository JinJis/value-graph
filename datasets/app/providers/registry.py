"""Resolve a concrete provider for a given (market, domain).

Providers are imported and instantiated lazily (and memoized) so that, e.g.,
importing pykrx only happens when a KR endpoint is actually hit. Price-provider
selection honors the ``*_PROVIDER_US`` / ``*_PROVIDER_KR`` settings; everything
else uses the free default for the market.
"""

from __future__ import annotations

from functools import cache

from app.config import settings
from app.errors import not_implemented
from app.providers.base import (
    CompanyProvider,
    EarningsProvider,
    FilingsProvider,
    FinancialsProvider,
    InsiderProvider,
    InstitutionalProvider,
    MacroProvider,
    MetricsProvider,
    NewsProvider,
    PricesProvider,
)
from app.symbols import Market


def _unbuilt(domain: str, market: Market):
    raise not_implemented(
        f"The '{domain}' endpoint is not yet implemented for market {market.value}."
    )


# --- Company -------------------------------------------------------------
@cache
def get_company_provider(market: Market) -> CompanyProvider:
    if market is Market.US:
        from app.providers.us.sec_edgar import SecEdgarProvider

        return SecEdgarProvider()
    if market is Market.KR:
        from app.providers.kr.opendart import OpenDartProvider

        return OpenDartProvider()
    _unbuilt("company", market)


# --- Prices --------------------------------------------------------------
@cache
def get_prices_provider(market: Market) -> PricesProvider:
    if market is Market.US:
        choice = settings.prices_provider_us
        if choice == "yahoo":
            from app.providers.us.yahoo import YahooProvider

            return YahooProvider()
        if choice == "stooq":
            from app.providers.us.stooq import StooqProvider

            return StooqProvider()
        _unbuilt(f"prices(provider={choice})", market)
    if market is Market.KR:
        choice = settings.prices_provider_kr
        if choice == "pykrx":
            from app.providers.kr.krx import PyKrxProvider

            return PyKrxProvider()
        if choice == "yahoo":
            from app.providers.us.yahoo import YahooProvider

            return YahooProvider()
        _unbuilt(f"prices(provider={choice})", market)
    _unbuilt("prices", market)


# --- Financial statements -----------------------------------------------
@cache
def get_financials_provider(market: Market) -> FinancialsProvider:
    if market is Market.US:
        from app.providers.us.sec_edgar import SecEdgarProvider

        return SecEdgarProvider()
    if market is Market.KR:
        from app.providers.kr.opendart import OpenDartProvider

        return OpenDartProvider()
    _unbuilt("financials", market)


# --- Filings -------------------------------------------------------------
@cache
def get_filings_provider(market: Market) -> FilingsProvider:
    if market is Market.US:
        from app.providers.us.sec_edgar import SecEdgarProvider

        return SecEdgarProvider()
    if market is Market.KR:
        from app.providers.kr.opendart import OpenDartProvider

        return OpenDartProvider()
    _unbuilt("filings", market)


# --- Macro ---------------------------------------------------------------
@cache
def get_macro_provider(market: Market) -> MacroProvider:
    if market is Market.US:
        from app.providers.us.fred import FredProvider

        return FredProvider()
    if market is Market.KR:
        from app.providers.kr.ecos import EcosProvider

        return EcosProvider()
    _unbuilt("macro", market)


# --- Metrics -------------------------------------------------------------
@cache
def get_metrics_provider(market: Market) -> MetricsProvider:
    if market is Market.KR:
        from app.providers.kr.opendart import OpenDartMetricsProvider

        return OpenDartMetricsProvider()
    if market is Market.US:
        from app.providers.us.sec_edgar import SecEdgarMetricsProvider

        return SecEdgarMetricsProvider()
    _unbuilt("financial-metrics", market)


# --- News ----------------------------------------------------------------
@cache
def get_news_provider(market: Market) -> NewsProvider:
    from app.providers.news import GoogleNewsProvider

    return GoogleNewsProvider()


# --- Earnings ------------------------------------------------------------
@cache
def get_earnings_provider(market: Market) -> EarningsProvider:
    if market is Market.US:
        from app.providers.us.sec_edgar import SecEdgarEarningsProvider

        return SecEdgarEarningsProvider()
    if market is Market.KR:
        from app.providers.kr.opendart import OpenDartEarningsProvider

        return OpenDartEarningsProvider()
    _unbuilt("earnings", market)


# --- Insider trades ------------------------------------------------------
@cache
def get_insider_provider(market: Market) -> InsiderProvider:
    if market is Market.US:
        from app.providers.us.sec_edgar import SecEdgarInsiderProvider

        return SecEdgarInsiderProvider()
    if market is Market.KR:
        from app.providers.kr.opendart import OpenDartInsiderProvider

        return OpenDartInsiderProvider()
    _unbuilt("insider-trades", market)


# --- Institutional holdings (13F) ---------------------------------------
@cache
def get_institutional_provider(market: Market) -> InstitutionalProvider:
    if market is Market.US:
        from app.providers.us.sec_edgar import SecEdgar13FProvider

        return SecEdgar13FProvider()
    _unbuilt("institutional-holdings", market)
