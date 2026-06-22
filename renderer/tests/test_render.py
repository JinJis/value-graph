"""Renderer service tests — routing + PDF normalization (render_pdf is patched, no Chromium)."""

import app.main as M
from fastapi.testclient import TestClient

client = TestClient(M.app)


def test_health():
    assert client.get("/health").json()["ok"] is True


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
