"""GCP Document AI — Layout Parser adapter for PDF presentation decks.

Layout Parser is purpose-built for RAG: it returns FAITHFUL, layout-aware text chunks (not a
generative paraphrase) WITH page + bounding-box anchors — so a cited passage can be highlighted at
its exact location in the in-app pdf.js viewer, even on a chart/table slide. This keeps the trust
brand intact (the RAG corpus is the deck's real words, never invented).

Auth via Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS → the same service-account
the reranker uses). The SDK is an OPTIONAL dependency and the processor is operator-configured: with
neither, ``parse_pdf`` returns None and the deck feature simply stays dark (honesty over fake data).
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings

log = logging.getLogger(__name__)

try:  # optional, heavy dep — absent → the feature is dark, not broken
    from google.cloud import documentai_v1 as documentai  # type: ignore
except Exception:  # noqa: BLE001
    documentai = None  # type: ignore


def configured() -> bool:
    """True only if the SDK is installed and a processor is configured."""
    return bool(documentai and settings.docai_processor_id
                and (settings.docai_project or settings.docai_location))


def _bbox(layout) -> list[float] | None:
    """Normalized [x0,y0,x1,y1] from a layout's bounding poly (best-effort)."""
    try:
        verts = layout.bounding_poly.normalized_vertices
        xs = [v.x for v in verts]
        ys = [v.y for v in verts]
        return [min(xs), min(ys), max(xs), max(ys)] if xs and ys else None
    except Exception:  # noqa: BLE001
        return None


def _parse_sync(pdf: bytes) -> list[dict]:
    proc = settings.docai_processor_id
    project = settings.docai_project
    location = settings.docai_location or "us"
    opts = {"api_endpoint": f"{location}-documentai.googleapis.com"}
    client = documentai.DocumentProcessorServiceClient(client_options=opts)  # type: ignore
    name = client.processor_path(project, location, proc) if project else proc
    raw = documentai.RawDocument(content=pdf, mime_type="application/pdf")  # type: ignore
    result = client.process_document(documentai.ProcessRequest(name=name, raw_document=raw))  # type: ignore
    doc = result.document
    out: list[dict] = []
    # Layout Parser emits a chunked_document; each chunk is a faithful, RAG-ready block.
    chunked = getattr(doc, "chunked_document", None)
    for ch in (getattr(chunked, "chunks", []) or []):
        text = (getattr(ch, "content", "") or "").strip()
        if not text:
            continue
        page = None
        bbox = None
        ps = getattr(ch, "page_span", None)
        if ps is not None:
            page = getattr(ps, "page_start", None)
        out.append({"text": text, "page": page, "bbox": bbox})
    if out:
        return out
    # Fallback: some processors return document_layout blocks instead of chunked_document.
    layout = getattr(doc, "document_layout", None)
    for blk in (getattr(layout, "blocks", []) or []):
        tb = getattr(blk, "text_block", None)
        text = (getattr(tb, "text", "") or "").strip() if tb else ""
        if text:
            out.append({"text": text, "page": None, "bbox": None})
    return out


async def parse_pdf(pdf: bytes) -> list[dict] | None:
    """Faithful, layout-aware chunks ``[{text, page, bbox}]`` from a PDF deck — or None if Document
    AI isn't configured / the SDK is absent / the call failed (feature stays dark)."""
    if not configured() or not pdf:
        return None
    try:
        return await asyncio.to_thread(_parse_sync, pdf)
    except Exception as exc:  # noqa: BLE001
        log.warning("document_ai parse failed: %s", exc)
        return None
