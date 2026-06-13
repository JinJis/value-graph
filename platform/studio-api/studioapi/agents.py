"""Configurable agents (F1): provided templates + per-user CRUD.

An agent bundles a model (``stub``/``gemini``), a system prompt, and a set of
data sources (connector ids). When a chat runs with an agent, these become the
``AgentSpec`` sent to the agent engine, so the agent only uses the sources it was
given and follows its prompt.
"""

from __future__ import annotations

import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from studioapi.config import settings
from studioapi.db import SessionLocal
from studioapi.deps import current_user, require_service
from studioapi.models import Agent, User

router = APIRouter(prefix="/agents", tags=["Agents"], dependencies=[Depends(require_service)])


# --- provided templates (seeded once; user_email is None) -----------------
TEMPLATES: list[dict] = [
    {
        "id": "tpl_research", "name": "종합 리서치", "is_template": True, "model": "stub",
        "description": "공시·재무·시황·뉴스를 폭넓게 활용하는 기본 리서치 에이전트.",
        "system_prompt": "You answer investment-data questions with sourced facts across filings, "
                         "financials, prices, macro, and news. Always cite sources.",
        "data_sources": ["sec_edgar", "opendart", "yahoo", "fred", "ecos", "google_news", "datasets_store", "rag"],
    },
    {
        "id": "tpl_filings", "name": "공시·실적 분석", "is_template": True, "model": "stub",
        "description": "기업 공시와 재무제표 중심 — SEC EDGAR / OpenDART / RAG.",
        "system_prompt": "Focus on company filings and financial statements. Ground every claim in a "
                         "filing and cite it. Never give buy/sell advice.",
        "data_sources": ["sec_edgar", "opendart", "datasets_store", "rag"],
    },
    {
        "id": "tpl_market", "name": "시황·가격", "is_template": True, "model": "stub",
        "description": "가격 흐름과 시장 뉴스 — Yahoo / 뉴스 / 거시지표.",
        "system_prompt": "Focus on market prices and market-moving news with their sources. "
                         "Describe what happened; do not predict prices.",
        "data_sources": ["yahoo", "google_news", "fred", "ecos"],
    },
    {
        "id": "tpl_macro", "name": "거시경제", "is_template": True, "model": "stub",
        "description": "금리·물가 등 거시지표 — FRED(미국) / ECOS(한국).",
        "system_prompt": "Focus on macroeconomic indicators (rates, inflation, GDP) from FRED and the "
                         "Bank of Korea ECOS. Report figures with their as-of dates.",
        "data_sources": ["fred", "ecos", "google_news"],
    },
]


def seed_templates() -> None:
    """Insert the provided templates once (idempotent on id)."""
    with SessionLocal() as db:
        for t in TEMPLATES:
            if db.get(Agent, t["id"]):
                continue
            db.add(Agent(
                id=t["id"], user_email=None, name=t["name"], description=t["description"],
                model=t["model"], system_prompt=t["system_prompt"],
                data_sources=json.dumps(t["data_sources"]), is_template=True,
            ))
        db.commit()


# --- schemas --------------------------------------------------------------
class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    model: str = "stub"
    system_prompt: str | None = None
    data_sources: list[str] = []


class AgentPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    data_sources: list[str] | None = None


def _out(a: Agent) -> dict:
    return {
        "id": a.id, "name": a.name, "description": a.description, "model": a.model,
        "system_prompt": a.system_prompt, "data_sources": json.loads(a.data_sources) if a.data_sources else [],
        "is_template": a.is_template, "editable": a.user_email is not None,
    }


def agent_to_spec(a: Agent) -> dict:
    """Map a stored agent to the agent-engine ``AgentSpec`` payload."""
    return {
        "system": a.system_prompt,
        "allowed_tools": json.loads(a.data_sources) if a.data_sources else None,
        "backend": a.model or None,
    }


def load_agent(db, agent_id: str, email: str) -> Agent | None:
    """Fetch an agent the user may use: their own, or a provided template."""
    a = db.get(Agent, agent_id)
    if a is None or (a.user_email is not None and a.user_email != email):
        return None
    return a


# --- endpoints ------------------------------------------------------------
@router.get("", summary="List provided templates + the user's own agents")
async def list_agents(user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(Agent).where(or_(Agent.user_email == user.email, Agent.user_email.is_(None)))
            .order_by(Agent.is_template.desc(), Agent.created_at.desc())
        ).scalars().all()
        return {"agents": [_out(a) for a in rows]}


@router.post("", summary="Create an agent")
async def create_agent(body: AgentIn, user: User = Depends(current_user)) -> dict:
    if body.model not in ("stub", "gemini"):
        raise HTTPException(422, "model must be 'stub' or 'gemini'.")
    agent = Agent(
        user_email=user.email, name=body.name, description=body.description, model=body.model,
        system_prompt=body.system_prompt, data_sources=json.dumps(body.data_sources), is_template=False,
    )
    with SessionLocal() as db:
        db.add(agent)
        db.commit()
        return _out(agent)


@router.get("/{agent_id}", summary="Get one agent")
async def get_agent(agent_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        a = load_agent(db, agent_id, user.email)
        if a is None:
            raise HTTPException(404, "Agent not found.")
        return _out(a)


@router.patch("/{agent_id}", summary="Update an agent (own only)")
async def update_agent(agent_id: str, body: AgentPatch, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        a = db.get(Agent, agent_id)
        if a is None or a.user_email != user.email:
            raise HTTPException(404, "Agent not found or not editable.")  # templates aren't editable
        if body.model is not None and body.model not in ("stub", "gemini"):
            raise HTTPException(422, "model must be 'stub' or 'gemini'.")
        if body.name is not None:
            a.name = body.name
        if body.description is not None:
            a.description = body.description
        if body.model is not None:
            a.model = body.model
        if body.system_prompt is not None:
            a.system_prompt = body.system_prompt
        if body.data_sources is not None:
            a.data_sources = json.dumps(body.data_sources)
        db.commit()
        return _out(a)


@router.delete("/{agent_id}", summary="Delete an agent (own only)")
async def delete_agent(agent_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        a = db.get(Agent, agent_id)
        if a is None or a.user_email != user.email:
            raise HTTPException(404, "Agent not found or not deletable.")
        db.delete(a)
        db.commit()
        return {"deleted": agent_id}


# --- connectors (data-source picker) --------------------------------------
connectors_router = APIRouter(tags=["Agents"], dependencies=[Depends(require_service)])


@connectors_router.get("/connectors", summary="Data sources available to build agents")
async def list_connectors() -> dict:
    """Proxy the control-plane catalog so the builder can show selectable sources."""
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(f"{settings.control_plane_url}/catalog")
            resp.raise_for_status()
            connectors = resp.json().get("connectors", [])
    except httpx.HTTPError:
        return {"connectors": []}
    return {"connectors": [
        {"id": c["id"], "name": c.get("name", c["id"]), "description": c.get("description")}
        for c in connectors
    ]}
