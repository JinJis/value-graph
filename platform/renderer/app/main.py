"""Evidence renderer service (PH-PROV2).

Internal-only microservice (reached from `datasets` via RENDERER_URL). Turns a precomputed
fact locator into a highlighted screenshot of the real filing, cached on a volume so the
expensive headless render happens at most once per (accession, locator).
"""

from __future__ import annotations

import os
import pathlib

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.render import cache_key, render_sec

app = FastAPI(title="ValueGraph Renderer", version="0.1.0")

SEC_UA = os.getenv("SEC_EDGAR_USER_AGENT", "ValueGraph Renderer contact@example.com")


def _cache_dir() -> pathlib.Path:
    p = pathlib.Path(os.getenv("RENDER_CACHE_DIR", "/cache"))
    p.mkdir(parents=True, exist_ok=True)
    return p


class RenderRequest(BaseModel):
    doc_url: str | None = None
    accession: str
    element_id: str | None = None
    selector: str | None = None
    html: str | None = None   # caller-supplied filing HTML (preferred; SEC 403s Chromium directly)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "renderer"}


@app.post("/render/sec")
async def render(req: RenderRequest):
    """Cache-first highlighted screenshot of a SEC iXBRL element. 502 on render failure."""
    locator = req.element_id or req.selector or ""
    if not locator:
        return JSONResponse({"error": "no locator"}, status_code=400)
    path = _cache_dir() / f"{cache_key(req.accession, locator)}.png"
    if path.exists():
        return Response(content=path.read_bytes(), media_type="image/png", headers={"x-cache": "hit"})
    try:
        result = await render_sec(req.doc_url, req.element_id, req.selector, ua=SEC_UA, html=req.html)
    except Exception as exc:  # noqa: BLE001 — never 500; datasets maps 502 → 204 → UI text fallback
        return JSONResponse({"error": str(exc)[:200]}, status_code=502)
    if not result:
        return JSONResponse({"error": "no locator"}, status_code=502)
    png, meta = result
    path.write_bytes(png)
    return Response(content=png, media_type="image/png",
                    headers={"x-cache": "miss", "x-evidence-bbox": str(meta.get("bbox") or "")})
