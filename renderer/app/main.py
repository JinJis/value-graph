"""Evidence renderer service (PH-PROV3).

Internal-only microservice (reached from `datasets` via RENDERER_URL). Its one job is to
normalize a filing document (US iXBRL HTML) to **PDF** at ingest, one-shot — the heavy
headless-Chromium step is isolated here so query-time evidence highlighting (PyMuPDF in
`datasets`) stays browser-free. KR uses DART's official PDF and never touches this service.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.render import render_pdf

app = FastAPI(title="ValueGraph Renderer", version="0.2.0")

SEC_UA = os.getenv("SEC_EDGAR_USER_AGENT", "ValueGraph Renderer contact@example.com")


class PdfRequest(BaseModel):
    html: str | None = None        # filing HTML / DART markup (preferred)
    doc_url: str | None = None     # fallback: let Chromium fetch it


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "renderer"}


@app.post("/pdf/from-html")
async def pdf_from_html(req: PdfRequest):
    """PH-PROV3: normalize a filing document to PDF at ingest (one-shot). 502 on failure."""
    if not (req.html or req.doc_url):
        return JSONResponse({"error": "no html or doc_url"}, status_code=400)
    try:
        pdf = await render_pdf(html=req.html, doc_url=req.doc_url, ua=SEC_UA)
    except Exception as exc:  # noqa: BLE001 — never 500; datasets skips storing on 502
        return JSONResponse({"error": str(exc)[:200]}, status_code=502)
    return Response(content=pdf, media_type="application/pdf", headers={"content-disposition": "inline"})
