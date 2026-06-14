"""RAG ingestion pipeline.

Fetches news for all companies on the tenants' watchlists (plus broad market news)
and ingests them into the RAG service via the control-plane gateway.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
from sqlalchemy import select

from studioapi.config import settings
from studioapi.db import SessionLocal
from studioapi.models import User, Watchlist, WatchlistItem

logger = logging.getLogger(__name__)


async def run_rag_ingestion_for_user(user: User) -> int:
    # 1) Get unique tickers in user's watchlists
    with SessionLocal() as db:
        items = db.execute(
            select(WatchlistItem.market, WatchlistItem.ticker)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_email == user.email)
        ).all()

    # Get unique market, ticker tuples
    tickers = list(set((item.market, item.ticker) for item in items))

    # Also add None ticker for broad market news (both US and KR by default)
    tickers.append(("US", None))
    tickers.append(("KR", None))

    headers = {"X-API-KEY": user.api_key}
    total_chunks = 0

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        for market, ticker in tickers:
            params: dict[str, Any] = {"market": market, "limit": 10}
            if ticker:
                params["ticker"] = ticker

            try:
                # Call news connector via the gateway
                resp = await client.get(
                    f"{settings.control_plane_url}/news",
                    params=params,
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Failed to fetch news for {market}:{ticker} via gateway: {resp.status_code} - {resp.text}"
                    )
                    continue
                news_data = resp.json().get("news", [])
            except Exception as e:
                logger.error(f"Error fetching news for {market}:{ticker}: {e}")
                continue

            if not news_data:
                continue

            # Convert to IngestDoc structure
            documents = []
            for item in news_data:
                text = item.get("title")
                url = item.get("url")
                if not text or not url:
                    continue
                url_hash = hashlib.md5(url.encode()).hexdigest()
                documents.append({
                    "text": text,
                    "doc_id": f"news_{market}_{ticker or 'market'}_{url_hash}",
                    "source": item.get("source") or "Google News",
                    "doc_type": "news",
                    "ticker": ticker,
                    "market": market,
                    "as_of": item.get("date"),
                    "url": url,
                })

            if not documents:
                continue

            # Ingest to RAG via the gateway (entitled, metered, and isolates by X-Tenant-Id)
            try:
                resp = await client.post(
                    f"{settings.control_plane_url}/rag/ingest",
                    json={"documents": documents},
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Failed to ingest RAG for {market}:{ticker} via gateway: {resp.status_code} - {resp.text}"
                    )
                    continue
                total_chunks += resp.json().get("chunks", 0)
            except Exception as e:
                logger.error(f"Error ingesting RAG for {market}:{ticker}: {e}")

    return total_chunks


async def run_rag_ingestion_pipeline() -> dict[str, int]:
    with SessionLocal() as db:
        users = db.execute(select(User)).scalars().all()

    summary = {}
    for user in users:
        try:
            chunks = await run_rag_ingestion_for_user(user)
            summary[user.email] = chunks
        except Exception as e:
            logger.error(f"Failed RAG ingestion pipeline for user {user.email}: {e}")
            summary[user.email] = -1

    return summary
