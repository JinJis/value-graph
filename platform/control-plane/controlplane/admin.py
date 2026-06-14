"""Admin / management endpoints (guarded by the X-Admin-Token header).

Create tenants → projects → API keys, and activate connectors per project. These
are platform-operator actions; tenant self-service UI can wrap them later.
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from controlplane.auth import generate_key
from controlplane.config import settings
from controlplane.db import SessionLocal
from controlplane.models import Activation, ApiKey, AuditLog, Project, Tenant, UsageEvent


async def require_admin(x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> None:
    if not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(401, "Invalid admin token.")


router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


class NameIn(BaseModel):
    name: str


class KeyIn(BaseModel):
    name: str = "key"
    scopes: str = "read"


class ActivationIn(BaseModel):
    connector_id: str
    enabled: bool = True
    byo_credentials: str | None = None


@router.post("/tenants", summary="Create a tenant")
async def create_tenant(body: NameIn) -> dict:
    with SessionLocal() as db:
        t = Tenant(name=body.name)
        db.add(t)
        db.commit()
        return {"id": t.id, "name": t.name}


@router.post("/tenants/{tenant_id}/projects", summary="Create a project")
async def create_project(tenant_id: str, body: NameIn) -> dict:
    with SessionLocal() as db:
        if db.get(Tenant, tenant_id) is None:
            raise HTTPException(404, "Unknown tenant.")
        p = Project(tenant_id=tenant_id, name=body.name)
        db.add(p)
        db.commit()
        return {"id": p.id, "tenant_id": tenant_id, "name": p.name}


@router.post("/projects/{project_id}/keys", summary="Create an API key (shown once)")
async def create_key(project_id: str, body: KeyIn) -> dict:
    with SessionLocal() as db:
        if db.get(Project, project_id) is None:
            raise HTTPException(404, "Unknown project.")
        full, prefix, key_hash = generate_key()
        k = ApiKey(project_id=project_id, name=body.name, prefix=prefix, key_hash=key_hash, scopes=body.scopes)
        db.add(k)
        db.commit()
        return {"id": k.id, "project_id": project_id, "api_key": full, "note": "Store this now — it is not retrievable later."}


@router.post("/projects/{project_id}/activations", summary="Activate a connector for a project")
async def activate(project_id: str, body: ActivationIn) -> dict:
    with SessionLocal() as db:
        if db.get(Project, project_id) is None:
            raise HTTPException(404, "Unknown project.")
        existing = db.execute(
            select(Activation).where(Activation.project_id == project_id, Activation.connector_id == body.connector_id)
        ).scalar_one_or_none()
        if existing:
            existing.enabled = body.enabled
            existing.byo_credentials = body.byo_credentials
            db.commit()
            act = existing
        else:
            act = Activation(project_id=project_id, connector_id=body.connector_id, enabled=body.enabled, byo_credentials=body.byo_credentials)
            db.add(act)
            db.commit()
        return {"id": act.id, "project_id": project_id, "connector_id": act.connector_id, "enabled": act.enabled}


@router.get("/projects/{project_id}/activations", summary="List project activations")
async def list_activations(project_id: str) -> dict:
    with SessionLocal() as db:
        rows = db.execute(select(Activation).where(Activation.project_id == project_id)).scalars().all()
        return {"activations": [{"connector_id": a.connector_id, "enabled": a.enabled} for a in rows]}


@router.get("/projects/{project_id}/usage", summary="Usage + cost summary")
async def usage(project_id: str) -> dict:
    with SessionLocal() as db:
        total_calls = db.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == project_id)) or 0
        total_cost = db.scalar(select(func.coalesce(func.sum(UsageEvent.cost_units), 0)).where(UsageEvent.project_id == project_id)) or 0
        by_conn = db.execute(
            select(UsageEvent.connector_id, func.count(), func.coalesce(func.sum(UsageEvent.cost_units), 0))
            .where(UsageEvent.project_id == project_id).group_by(UsageEvent.connector_id)
        ).all()
        return {
            "project_id": project_id,
            "total_calls": total_calls,
            "total_cost_units": int(total_cost),
            "by_connector": [{"connector_id": c, "calls": n, "cost_units": int(cost)} for c, n, cost in by_conn],
        }


@router.get("/projects/{project_id}/audit", summary="Recent audit log")
async def audit(project_id: str, limit: int = 50) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(AuditLog).where(AuditLog.project_id == project_id).order_by(AuditLog.id.desc()).limit(limit)
        ).scalars().all()
        return {"audit": [{"action": a.action, "detail": a.detail} for a in rows]}


@router.get("/catalog", summary="Proxy the data-plane catalog (what can be activated)")
async def catalog() -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(f"{settings.datasets_url}/catalog")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Data plane catalog unavailable: {exc}")
