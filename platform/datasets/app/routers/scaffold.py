"""Scaffolded endpoints.

These paths are defined in the API surface but are not
yet backed by a real provider in this build. They are registered (so they appear
in ``/docs`` and the generated OpenAPI) and return a clear HTTP 501 rather than
fabricated data. As each provider lands, move its path out of this module into a
real router.
"""

from __future__ import annotations

import re

from fastapi import APIRouter

from app.errors import NOT_IMPLEMENTED_TAG, not_implemented

router = APIRouter()

# (path, tag) — registered as 501s grouped by their spec tag.
_UNBUILT_GET: list[tuple[str, str]] = [
    ("/institutional-holdings/investors", "Institutional Holdings"),
    ("/institutional-holdings/tickers", "Institutional Holdings"),
    ("/index-funds", "Index Funds"),
    ("/index-funds/tickers", "Index Funds"),
    ("/financials/search/screener/filters", "Financial Statements"),
    ("/financials/income-statements/segments", "Financial Statements"),
    ("/financials/balance-sheets/segments", "Financial Statements"),
    ("/financials/cash-flow-statements/segments", "Financial Statements"),
    ("/financials/segments", "Financial Statements"),
    ("/financials/income-statements/as-reported", "Financial Statements"),
    ("/financials/balance-sheets/as-reported", "Financial Statements"),
    ("/financials/cash-flow-statements/as-reported", "Financial Statements"),
    ("/filings/items", "SEC Filings"),
    ("/filings/items/types", "SEC Filings"),
    ("/kpi/metrics", "KPIs"),
    ("/kpi/metrics/tickers", "KPIs"),
    ("/kpi/metrics/sectors", "KPIs"),
    ("/kpi/guidance", "KPIs"),
    ("/kpi/non-gaap", "KPIs"),
]
_UNBUILT_POST: list[tuple[str, str]] = []


def _slugged(path: str, method: str):
    async def handler():
        raise not_implemented(
            f"{method} {path} is part of the published API surface but is not yet "
            "implemented in this build."
        )

    handler.__name__ = method.lower() + "_" + re.sub(r"[^a-z0-9]+", "_", path.strip("/").lower())
    return handler


def _register(path: str, tag: str, method: str) -> None:
    router.add_api_route(
        path,
        _slugged(path, method),
        methods=[method],
        tags=[NOT_IMPLEMENTED_TAG],
        summary=f"🚧 NOT IMPLEMENTED — {method} {path}",
        description=(
            f"**Not implemented yet** (spec group: _{tag}_). This endpoint is part of the "
            "published API surface but is not yet backed by real data — it returns **HTTP 501**. "
            "Everything not under this tag is implemented and returns real data."
        ),
        status_code=501,
    )


for _path, _tag in _UNBUILT_GET:
    _register(_path, _tag, "GET")
for _path, _tag in _UNBUILT_POST:
    _register(_path, _tag, "POST")
