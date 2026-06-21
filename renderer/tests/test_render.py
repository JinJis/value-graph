"""Renderer service tests — cache + routing, no Chromium launched (render_sec is patched)."""

import app.main as M
from app.render import HIGHLIGHT_CSS, RENDERER_VERSION, cache_key
from fastapi.testclient import TestClient

client = TestClient(M.app)


def test_cache_key_stable_and_version_sensitive(monkeypatch):
    k1 = cache_key("0000320193-24-000123", "#f-rev-cur")
    assert k1 == cache_key("0000320193-24-000123", "#f-rev-cur")     # deterministic
    assert k1 != cache_key("0000320193-24-000123", "#other")          # locator-sensitive
    assert "outline" in HIGHLIGHT_CSS and "#D9A300" in HIGHLIGHT_CSS  # amber highlight
    assert RENDERER_VERSION                                            # set


def test_health():
    assert client.get("/health").json()["ok"] is True


def test_render_requires_a_locator():
    r = client.post("/render/sec", json={"doc_url": "https://x", "accession": "a"})
    assert r.status_code == 400


def test_render_miss_then_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    async def fake_render(doc_url=None, element_id=None, selector=None, ua=None, html=None):
        calls["n"] += 1
        return b"\x89PNG-fake", {"bbox": {"x": 1, "y": 2, "width": 3, "height": 4}}

    monkeypatch.setattr(M, "render_sec", fake_render)
    body = {"doc_url": "https://sec.gov/x.htm", "accession": "0000320193-24-000123", "element_id": "f-rev-cur"}

    r1 = client.post("/render/sec", json=body)
    assert r1.status_code == 200 and r1.headers["content-type"] == "image/png"
    assert r1.headers["x-cache"] == "miss" and r1.content == b"\x89PNG-fake"

    r2 = client.post("/render/sec", json=body)   # served from disk cache, no second render
    assert r2.status_code == 200 and r2.headers["x-cache"] == "hit"
    assert calls["n"] == 1


def test_render_failure_is_502(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))

    async def boom(*a, **k):
        raise RuntimeError("selector not found")

    monkeypatch.setattr(M, "render_sec", boom)
    r = client.post("/render/sec", json={"doc_url": "https://x", "accession": "a", "selector": "//x"})
    assert r.status_code == 502 and "error" in r.json()


# --- PH-PROV3: ingest-time HTML→PDF normalization -------------------------
def test_pdf_from_html_requires_input():
    assert client.post("/pdf/from-html", json={}).status_code == 400


def test_pdf_from_html_returns_pdf(monkeypatch):
    async def fake_pdf(html=None, doc_url=None, ua=None):
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(M, "render_pdf", fake_pdf)
    r = client.post("/pdf/from-html", json={"html": "<TABLE><TR><TD>매출액</TD></TR></TABLE>"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-1.7 fake"


def test_pdf_from_html_failure_is_502(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("chromium crashed")

    monkeypatch.setattr(M, "render_pdf", boom)
    r = client.post("/pdf/from-html", json={"html": "<x/>"})
    assert r.status_code == 502 and "error" in r.json()
