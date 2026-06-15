"""Board (U3-03): live artifacts the user pinned.

Each pin stores the JSON artifact spec (kind/title/series/source/as_of/tool/args), so
the Board can re-render it and (U3-03b) re-fetch via its tool+args. Per-user scoped;
the web BFF authenticates with a service token and forwards the user's email.
"""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from studioapi.config import settings
from studioapi.db import SessionLocal
from studioapi.deps import current_user, require_service
from studioapi.models import PinnedArtifact, User

router = APIRouter(prefix="/board", tags=["Board"], dependencies=[Depends(require_service)])


class PinIn(BaseModel):
    spec: dict


def _row(p: PinnedArtifact) -> dict:
    return {"id": p.id, "title": p.title, "spec": json.loads(p.spec),
            "created_at": p.created_at.isoformat() if p.created_at else None}


@router.get("", summary="List the user's pinned artifacts (the Board)")
async def list_pins(user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(PinnedArtifact).where(PinnedArtifact.user_email == user.email)
            .order_by(PinnedArtifact.created_at.desc())
        ).scalars().all()
        return {"pinned": [_row(p) for p in rows]}


@router.post("", summary="Pin an artifact to the Board")
async def pin(body: PinIn, user: User = Depends(current_user)) -> dict:
    if not body.spec.get("kind"):
        raise HTTPException(422, "spec must be an artifact (missing 'kind').")
    title = str(body.spec.get("title") or "Untitled")[:200]
    with SessionLocal() as db:
        p = PinnedArtifact(user_email=user.email, title=title,
                           spec=json.dumps(body.spec, ensure_ascii=False))
        db.add(p)
        db.commit()
        db.refresh(p)
        return _row(p)


@router.post("/{pin_id}/refresh", summary="Re-fetch a pinned artifact (live, new as_of)")
async def refresh_pin(pin_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = db.get(PinnedArtifact, pin_id)
        if p is None or p.user_email != user.email:
            raise HTTPException(404, "Pinned artifact not found.")
        spec = json.loads(p.spec)
    tool = spec.get("tool")
    if not tool:
        raise HTTPException(400, "This pin has no tool to refresh.")
    # re-run the tool through the agent engine with the user's tenant key (entitled + metered)
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.agent_engine_url}/agent/artifact/refresh",
                json={"tool": tool, "args": spec.get("args") or {}, "title": spec.get("title")},
                headers={"X-API-KEY": user.api_key},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Refresh failed: {exc}")
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, "Refresh failed upstream.")
    fresh = (resp.json() or {}).get("artifact")
    if not fresh:
        raise HTTPException(502, "Refresh returned no artifact.")
    with SessionLocal() as db:
        p = db.get(PinnedArtifact, pin_id)
        p.spec = json.dumps(fresh, ensure_ascii=False)
        p.title = fresh.get("title") or p.title
        db.commit()
        db.refresh(p)
        return _row(p)


@router.delete("/{pin_id}", summary="Remove a pinned artifact")
async def unpin(pin_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = db.get(PinnedArtifact, pin_id)
        if p is None or p.user_email != user.email:
            raise HTTPException(404, "Pinned artifact not found.")
        db.delete(p)
        db.commit()
        return {"deleted": pin_id}
