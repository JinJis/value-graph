"""FastAPI application entrypoint.

A financialdatasets.ai-compatible API extended to the Korean market. Select the
market with the ``market`` query parameter (US default, KR for KOSPI/KOSDAQ).
"""

from __future__ import annotations

from fastapi import FastAPI

from app.errors import NOT_IMPLEMENTED_TAG, register_error_handlers
from app.routers import (
    company,
    earnings,
    filings,
    financials,
    insider,
    institutional,
    macro,
    metrics,
    news,
    prices,
    scaffold,
)

app = FastAPI(
    title="ValueGraph Datasets API (US + Korea)",
    version="0.1.0",
    description=(
        "Financial datasets API modeled on financialdatasets.ai and extended to "
        "the Korean equity market (KOSPI/KOSDAQ). Use the `market` query parameter "
        "(`US` default, `KR`). **Not investment advice.**\n\n"
        "**Implementation status:** endpoints grouped under the "
        f"**{NOT_IMPLEMENTED_TAG}** tag (at the bottom) are not yet backed by real "
        "data and return HTTP 501. Everything in the other groups is implemented and "
        "returns real data (some endpoints need an upstream API key — see the README)."
    ),
    openapi_tags=[
        {
            "name": NOT_IMPLEMENTED_TAG,
            "description": (
                "These endpoints are part of the published financialdatasets.ai surface "
                "but are **not implemented yet** — every one returns **HTTP 501**. "
                "Use this section to see at a glance what is not testable yet."
            ),
        }
    ],
)

register_error_handlers(app)

for module in (
    company, prices, financials, filings, macro, metrics,
    news, earnings, insider, institutional, scaffold,
):
    app.include_router(module.router)


@app.get("/", tags=["Meta"], summary="Service metadata")
async def root() -> dict:
    return {
        "service": "valuegraph-datasets",
        "version": app.version,
        "markets": ["US", "KR"],
        "docs": "/docs",
        "disclaimer": "Not investment advice. Prices are delayed/EOD by default.",
    }


@app.get("/health", tags=["Meta"], summary="Health check")
async def health() -> dict:
    return {"status": "ok"}
