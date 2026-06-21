"""Superinvestor ("거장") 13F portfolios (PH-DATA-1).

`GET /gurus` lists the curated famous investors; `?slug=` returns that investor's latest
13F holdings (reusing the 13F provider) — every position carries its `accession_number`, so
the agent cites each holding to the real SEC filing (provenance, not an opaque feed).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep
from app.errors import not_found
from app.providers.registry import get_institutional_provider
from app.providers.us.gurus import get_guru, list_gurus
from app.symbols import Market

router = APIRouter(tags=["Superinvestors"])


@router.get(
    "/gurus",
    dependencies=[ApiKeyDep],
    summary="Superinvestor (거장) 13F portfolios — Buffett, Burry, Ackman …",
    description=(
        "Omit `slug` to list the curated investors. With `?slug=buffett` (etc.) returns that "
        "investor's latest SEC 13F holdings — each position cited to the filing. US only."
    ),
)
async def gurus(
    slug: str | None = Query(None, description="Guru slug (e.g. buffett); omit to list all."),
    limit: int = Query(20, ge=1, le=200),
) -> dict:
    if not slug:
        return {"resource": "gurus", "gurus": list_gurus()}
    g = get_guru(slug)
    if not g:
        raise not_found(f"Unknown guru '{slug}'. See GET /gurus for the list.")
    holdings = await get_institutional_provider(Market.US).by_filer(g["cik"], limit)
    return {"guru": g, "filer_cik": g["cik"], "holdings": holdings}
