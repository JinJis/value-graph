"""Rendering core for the evidence renderer (PH-PROV3).

One job: normalize a filing document (HTML / DART markup) to PDF with headless Chromium,
at ingest time. The Playwright import is lazy so this module is unit-testable without a
browser. Query-time highlighting is done elsewhere (PyMuPDF in `datasets`), browser-free.
"""

from __future__ import annotations


async def render_pdf(html: str | None = None, doc_url: str | None = None, ua: str | None = None) -> bytes:
    """Normalize a filing document (HTML / DART markup) to PDF (one-shot, ingest time).

    Prefers caller-supplied `html` (datasets already fetched it with the right User-Agent),
    falling back to a `goto(doc_url)`. Raises on failure (the caller maps that to 502)."""
    from playwright.async_api import async_playwright  # lazy: keeps the module browser-free

    if not (html or doc_url):
        raise ValueError("no html or doc_url")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(user_agent=ua)
            if html:
                await page.set_content(html, wait_until="domcontentloaded", timeout=60_000)
            else:
                await page.goto(doc_url, wait_until="domcontentloaded", timeout=60_000)
            return await page.pdf(format="A4", print_background=True,
                                  margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        finally:
            await browser.close()
