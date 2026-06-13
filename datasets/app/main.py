"""FastAPI application entrypoint.

A financialdatasets.ai-compatible API extended to the Korean market. Select the
market with the ``market`` query parameter (US default, KR for KOSPI/KOSDAQ).
"""

from __future__ import annotations

from fastapi import FastAPI

from app.errors import register_error_handlers
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
        "(`US` default, `KR`). **Not investment advice.**"
    ),
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
