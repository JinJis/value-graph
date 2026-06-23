"""CE-8: portfolios — the user's holdings + a live dashboard/analytics.

CRUD over ``Portfolio``/``Holding`` (per-user), plus an analytics endpoint that values the book
live (current price via the gateway), shows allocation + unrealized gain, and backtests the
allocation over the ingested PriceBar store. All data flows through the gateway (entitled +
metered, invariant #2); descriptive only — no advice/forecast.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studioapi.config import settings
from studioapi.db import SessionLocal
from studioapi.deps import current_user, require_service
from studioapi.models import Holding, Portfolio, User

router = APIRouter(prefix="/portfolios", tags=["Portfolio"], dependencies=[Depends(require_service)])


class PortfolioIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class HoldingIn(BaseModel):
    market: str = "US"
    ticker: str = Field(min_length=1, max_length=32)
    name: str | None = None
    shares: float = 0.0
    cost_basis: float | None = None


def _hrow(h: Holding) -> dict:
    return {"id": h.id, "market": h.market, "ticker": h.ticker, "name": h.name,
            "shares": h.shares, "cost_basis": h.cost_basis}


def _own(db, portfolio_id: str, email: str) -> Portfolio:
    p = db.get(Portfolio, portfolio_id)
    if p is None or p.user_email != email:
        raise HTTPException(404, "Portfolio not found.")
    return p


@router.get("", summary="List the user's portfolios")
async def list_portfolios(user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(Portfolio).where(Portfolio.user_email == user.email).order_by(Portfolio.created_at)
        ).scalars().all()
        out = []
        for p in rows:
            n = len(db.execute(select(Holding).where(Holding.portfolio_id == p.id)).scalars().all())
            out.append({"id": p.id, "name": p.name, "holdings": n})
        return {"portfolios": out}


@router.post("", summary="Create a portfolio")
async def create_portfolio(body: PortfolioIn, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = Portfolio(user_email=user.email, name=body.name)
        db.add(p)
        db.commit()
        db.refresh(p)
        return {"id": p.id, "name": p.name, "holdings": 0}


@router.delete("/{portfolio_id}", summary="Delete a portfolio + its holdings")
async def delete_portfolio(portfolio_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        _own(db, portfolio_id, user.email)
        for h in db.execute(select(Holding).where(Holding.portfolio_id == portfolio_id)).scalars().all():
            db.delete(h)
        db.delete(db.get(Portfolio, portfolio_id))
        db.commit()
        return {"deleted": portfolio_id}


@router.get("/{portfolio_id}", summary="Portfolio detail (holdings)")
async def get_portfolio(portfolio_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = _own(db, portfolio_id, user.email)
        hs = db.execute(select(Holding).where(Holding.portfolio_id == portfolio_id)).scalars().all()
        return {"id": p.id, "name": p.name, "holdings": [_hrow(h) for h in hs]}


@router.post("/{portfolio_id}/holdings", summary="Add/replace a holding")
async def add_holding(portfolio_id: str, body: HoldingIn, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        _own(db, portfolio_id, user.email)
        tk = body.ticker.upper()
        existing = db.execute(select(Holding).where(
            Holding.portfolio_id == portfolio_id, Holding.market == body.market.upper(),
            Holding.ticker == tk)).scalars().first()
        if existing:  # upsert: editing a position
            existing.shares, existing.cost_basis = body.shares, body.cost_basis
            existing.name = body.name or existing.name
            h = existing
        else:
            h = Holding(portfolio_id=portfolio_id, market=body.market.upper(), ticker=tk,
                        name=body.name, shares=body.shares, cost_basis=body.cost_basis)
            db.add(h)
        db.commit()
        db.refresh(h)
        return _hrow(h)


@router.delete("/{portfolio_id}/holdings/{holding_id}", summary="Remove a holding")
async def remove_holding(portfolio_id: str, holding_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        _own(db, portfolio_id, user.email)
        h = db.get(Holding, holding_id)
        if h is None or h.portfolio_id != portfolio_id:
            raise HTTPException(404, "Holding not found.")
        db.delete(h)
        db.commit()
        return {"deleted": holding_id}


async def _snapshot(client: httpx.AsyncClient, api_key: str, market: str, ticker: str) -> float | None:
    try:
        r = await client.get(f"{settings.control_plane_url}/prices/snapshot",
                             params={"ticker": ticker, "market": market}, headers={"X-API-KEY": api_key})
        if r.status_code == 200:
            return ((r.json() or {}).get("snapshot") or {}).get("price")
    except httpx.HTTPError:
        pass
    return None


async def _backtest(client: httpx.AsyncClient, api_key: str, market: str, weights: list[dict],
                    benchmark: str | None) -> dict | None:
    try:
        r = await client.post(f"{settings.control_plane_url}/backtest",
                              params={"market": market},
                              json={"holdings": weights, "benchmark": benchmark},
                              headers={"X-API-KEY": api_key})
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        pass
    return None


@router.get("/{portfolio_id}/analytics", summary="Live dashboard: value · allocation · backtest")
async def analytics(portfolio_id: str, benchmark: str | None = None, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = _own(db, portfolio_id, user.email)
        holdings = [_hrow(h) for h in db.execute(
            select(Holding).where(Holding.portfolio_id == portfolio_id)).scalars().all()]
    if not holdings:
        return {"id": p.id, "name": p.name, "positions": [], "total_value": 0.0, "note": "보유 종목이 없습니다."}

    # value the book live (current price per holding, concurrently, through the gateway)
    market = holdings[0]["market"]  # backtest is single-market; use the first holding's market
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        prices = await asyncio.gather(*[_snapshot(client, user.api_key, h["market"], h["ticker"]) for h in holdings])
        positions, total_value, total_cost = [], 0.0, 0.0
        for h, px in zip(holdings, prices):
            value = (px * h["shares"]) if (px is not None and h["shares"]) else None
            cost = (h["cost_basis"] * h["shares"]) if (h["cost_basis"] and h["shares"]) else None
            if value:
                total_value += value
            if cost:
                total_cost += cost
            positions.append({**h, "price": px, "value": value,
                              "gain": (value - cost) if (value is not None and cost is not None) else None})
        for pos in positions:  # weights once the total is known
            pos["weight"] = round(pos["value"] / total_value, 4) if (pos["value"] and total_value) else None

        # backtest the current allocation (weights) over the ingested store
        same_mkt = [pos for pos in positions if pos["market"] == market and pos.get("value")]
        weights = [{"ticker": pos["ticker"], "weight": pos["value"]} for pos in same_mkt]
        backtest = await _backtest(client, user.api_key, market, weights, benchmark) if weights else None

    return {
        "id": p.id, "name": p.name, "positions": positions,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if total_cost else None,
        "total_gain": round(total_value - total_cost, 2) if total_cost else None,
        "backtest": backtest,
        "disclaimer": "현재가 기반 평가 및 과거 성과입니다 — 미래 수익 보장·투자 조언이 아닙니다.",
    }
