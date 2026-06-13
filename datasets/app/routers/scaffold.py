"""Scaffolded endpoints.

These paths are part of the published financialdatasets.ai surface but are not
yet backed by a real provider in this build. They are registered (so they appear
in ``/docs`` and the generated OpenAPI) and return a clear HTTP 501 rather than
fabricated data. As each provider lands, move its path out of this module into a
real router.
"""

from __future__ import annotations

import re

from fastapi import APIRouter

from app.errors import not_implemented

router = APIRouter()

# (path, tag) — registered as 501s grouped by their spec tag.
_UNBUILT_GET: list[tuple[str, str]] = [
    ("/institutional-holdings/investors", "Institutional Holdings"),
    ("/institutional-holdings/tickers", "Institutional Holdings"),
    ("/index-funds", "Index Funds"),
    ("/index-funds/tickers", "Index Funds"),
    ("/earnings/tickers", "Earnings"),
    ("/financials/search/screener/filters", "Financial Statements"),
    ("/financials/income-statements/segments", "Financial Statements"),
    ("/financials/balance-sheets/segments", "Financial Statements"),
    ("/financials/cash-flow-statements/segments", "Financial Statements"),
    ("/financials/segments", "Financial Statements"),
    ("/financials/income-statements/as-reported", "Financial Statements"),
    ("/financials/balance-sheets/as-reported", "Financial Statements"),
    ("/financials/cash-flow-statements/as-reported", "Financial Statements"),
    ("/financials/as-reported", "Financial Statements"),
    ("/filings/items", "SEC Filings"),
    ("/filings/items/types", "SEC Filings"),
    ("/filings/tickers", "SEC Filings"),
    ("/filings/ciks", "SEC Filings"),
    ("/company/facts/ciks", "Company Information"),
    ("/prices/snapshot/market", "Market Data"),
    ("/kpi/metrics", "KPIs"),
    ("/kpi/metrics/tickers", "KPIs"),
    ("/kpi/metrics/sectors", "KPIs"),
    ("/kpi/guidance", "KPIs"),
    ("/kpi/non-gaap", "KPIs"),
]
_UNBUILT_POST: list[tuple[str, str]] = [
    ("/financials/search/screener", "Financial Statements"),
    ("/financials/search/line-items", "Financial Statements"),
]


def _slugged(path: str, method: str):
    async def handler():
        raise not_implemented(
            f"{method} {path} is part of the published API surface but is not yet "
            "implemented in this build."
        )

    handler.__name__ = method.lower() + "_" + re.sub(r"[^a-z0-9]+", "_", path.strip("/").lower())
    return handler


for _path, _tag in _UNBUILT_GET:
    router.add_api_route(
        _path, _slugged(_path, "GET"), methods=["GET"], tags=[_tag],
        summary=f"(not implemented) GET {_path}", status_code=501,
    )
for _path, _tag in _UNBUILT_POST:
    router.add_api_route(
        _path, _slugged(_path, "POST"), methods=["POST"], tags=[_tag],
        summary=f"(not implemented) POST {_path}", status_code=501,
    )
