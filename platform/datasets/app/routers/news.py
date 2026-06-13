"""News endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import NewsResponse
from app.providers.registry import get_news_provider
from app.symbols import Market, normalize_ticker

router = APIRouter(tags=["News"])


@router.get("/news", response_model=NewsResponse, dependencies=[ApiKeyDep])
async def get_news(
    ticker: str | None = Query(None, description="Company ticker; omit for broad market news."),
    limit: int = Query(5, ge=1, le=10, description="Max articles (default 5, max 10)."),
    market: MarketParam = Market.US,
) -> NewsResponse:
    norm = normalize_ticker(market, ticker) if ticker else None
    articles = await get_news_provider(market).news(market, norm, limit)
    return NewsResponse(news=articles)
