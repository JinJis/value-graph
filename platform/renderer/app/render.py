"""Rendering core for the evidence renderer (PH-PROV2).

Pure helpers (cache key, highlight CSS) are import-safe without a browser; the actual
Playwright render imports lazily so this module is unit-testable in a Chromium-less env.
Given a filing's primary iXBRL HTML URL + the precomputed element locator, it loads the
real document, highlights exactly that element, and screenshots its row/table region.
"""

from __future__ import annotations

import hashlib

# bump when the render output format changes → invalidates the on-disk cache
RENDERER_VERSION = "2"  # v2: crop a vertical band (highlighted row + context rows), not the lone row

# vertical context kept above & below the highlighted row, as a multiple of the row height
# (clamped to a pixel floor) so a 1-line row becomes a readable statement excerpt, not a sliver
_BAND_ROWS = 3
_BAND_MIN_PX = 54.0

# amber highlight (matches the web filing card's `--mark`/aging palette)
HIGHLIGHT_CSS = (
    ".vg-evidence-hl{outline:3px solid #D9A300 !important;"
    "background:rgba(245,210,90,.38) !important;"
    "box-shadow:0 0 0 6px rgba(245,210,90,.20) !important;border-radius:2px !important;}"
)


def cache_key(accession: str, locator: str) -> str:
    """Stable filename for a rendered evidence image (version-sensitive)."""
    raw = f"{RENDERER_VERSION}|{accession}|{locator}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


async def render_sec(doc_url: str | None = None, element_id: str | None = None, selector: str | None = None,
                     ua: str | None = None, html: str | None = None) -> tuple[bytes, dict] | None:
    """Highlight the target element and screenshot its row/table region.

    Prefers rendering `html` passed by the caller (datasets already fetched the filing with
    SEC's accepted User-Agent — SEC 403s headless Chromium directly), falling back to a
    `goto(doc_url)`. Returns (png_bytes, {bbox}) or None if no usable locator. Raises on
    render failure (the caller maps that to 502 → the UI degrades to the text card)."""
    from playwright.async_api import async_playwright  # lazy: keeps the module browser-free

    target = f"#{element_id}" if element_id else (f"xpath={selector}" if selector else None)
    if not target or not (html or doc_url):
        return None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(user_agent=ua, viewport={"width": 1280, "height": 1600})
            if html:
                await page.set_content(html, wait_until="domcontentloaded", timeout=30_000)
            else:
                await page.goto(doc_url, wait_until="domcontentloaded", timeout=30_000)
            loc = page.locator(target).first
            await loc.wait_for(state="attached", timeout=8_000)
            await page.add_style_tag(content=HIGHLIGHT_CSS)
            await loc.evaluate("el => el.classList.add('vg-evidence-hl')")
            await loc.scroll_into_view_if_needed(timeout=5_000)
            bbox = await loc.bounding_box()

            # Crop a vertical BAND: the highlighted row plus a few context rows above/below,
            # spanning the full table width (labels + period columns stay aligned). A lone row
            # is ~1264x19 — too thin to read as a thumbnail; a band reads as a real statement
            # excerpt and the highlight keeps its surrounding line items for context.
            png = None
            row = page.locator(f"{target} >> xpath=ancestor-or-self::tr[1]").first
            table = page.locator(f"{target} >> xpath=ancestor-or-self::table[1]").first
            if await row.count() and await table.count():
                rb, tb = await row.bounding_box(), await table.bounding_box()
                if rb and tb:
                    pad = max(rb["height"] * _BAND_ROWS, _BAND_MIN_PX)
                    top = max(tb["y"], rb["y"] - pad)
                    bottom = min(tb["y"] + tb["height"], rb["y"] + rb["height"] + pad)
                    clip = {"x": tb["x"], "y": top, "width": tb["width"],
                            "height": max(bottom - top, rb["height"])}
                    png = await page.screenshot(type="png", clip=clip, timeout=10_000)
            if png is None:  # fall back to the bare row, then the element itself
                shot_target = row if await row.count() else loc
                png = await shot_target.screenshot(type="png", timeout=10_000)
            return png, {"bbox": bbox}
        finally:
            await browser.close()
