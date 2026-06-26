"""Unit tests for the external-source evidence viewer (`app.store.source_html`).

The in-app source viewer fetches an arbitrary public page server-side, sanitizes it, and serves it
same-origin so the web viewer can highlight the cited value. These tests pin the SSRF guard (the
thing that makes fetching arbitrary URLs safe), the fragment stripping, and the sanitize+serve path.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.store import source_html as S


def _addrinfo(ip: str):
    # shape of socket.getaddrinfo entries: (family, type, proto, canonname, sockaddr)
    return [(2, 1, 6, "", (ip, 0))]


def test_strip_fragment_drops_text_anchor():
    u = "https://example.com/a/b?q=1#:~:text=hello%20world"
    assert S._strip_fragment(u) == "https://example.com/a/b?q=1"
    # no fragment → unchanged
    assert S._strip_fragment("https://example.com/x") == "https://example.com/x"


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254",
                                "::1", "0.0.0.0", "224.0.0.1"])
def test_is_public_host_rejects_private(monkeypatch, ip):
    monkeypatch.setattr(S.socket, "getaddrinfo", lambda *a, **k: _addrinfo(ip))
    assert S._is_public_host("anything.example") is False


def test_is_public_host_accepts_public(monkeypatch):
    monkeypatch.setattr(S.socket, "getaddrinfo", lambda *a, **k: _addrinfo("8.8.8.8"))
    assert S._is_public_host("data.bls.gov") is True


def test_is_public_host_unresolvable_is_refused(monkeypatch):
    def boom(*a, **k):
        raise S.socket.gaierror("nope")
    monkeypatch.setattr(S.socket, "getaddrinfo", boom)
    assert S._is_public_host("does-not-resolve.invalid") is False


def test_safe_rejects_non_http_schemes(monkeypatch):
    monkeypatch.setattr(S.socket, "getaddrinfo", lambda *a, **k: _addrinfo("8.8.8.8"))
    assert S._safe("file:///etc/passwd") is False
    assert S._safe("ftp://example.com/x") is False
    assert S._safe("https://example.com/ok") is True


@pytest.mark.asyncio
async def test_get_source_html_private_host_makes_no_request(monkeypatch, tmp_path):
    monkeypatch.setattr(S.settings, "evidence_docs_dir", str(tmp_path))
    monkeypatch.setattr(S.socket, "getaddrinfo", lambda *a, **k: _addrinfo("127.0.0.1"))
    # if it tried to fetch, respx (no routes) would raise; assert it returns None before fetching
    assert await S.get_source_html("http://localhost/evil") is None


@pytest.mark.asyncio
@respx.mock
async def test_get_source_html_sanitizes_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(S.settings, "evidence_docs_dir", str(tmp_path))
    monkeypatch.setattr(S.socket, "getaddrinfo", lambda *a, **k: _addrinfo("8.8.8.8"))
    page = ("<html><head><title>CPI</title>"
            "<meta http-equiv='Content-Security-Policy' content='default-src *'>"
            "<script>alert(1)</script></head>"
            "<body><table><tr><td>323.048</td></tr></table></body></html>")
    route = respx.get("https://data.bls.gov/timeseries/CUSR0000SA0").mock(
        return_value=httpx.Response(200, html=page))

    out = await S.get_source_html("https://data.bls.gov/timeseries/CUSR0000SA0#:~:text=323")
    assert out is not None
    assert "<script" not in out.lower()                 # scripts stripped
    assert "default-src 'none'" in out                  # our strict CSP injected
    assert "default-src *" not in out                   # source's own CSP dropped
    assert "323.048" in out                             # the cited value survives for highlighting
    assert route.called

    # second call is cache-first: served from disk without a second fetch
    respx.reset()
    cached = await S.get_source_html("https://data.bls.gov/timeseries/CUSR0000SA0#:~:text=999")
    assert cached is not None and "323.048" in cached


@pytest.mark.asyncio
@respx.mock
async def test_get_source_html_rejects_non_html(monkeypatch, tmp_path):
    monkeypatch.setattr(S.settings, "evidence_docs_dir", str(tmp_path))
    monkeypatch.setattr(S.socket, "getaddrinfo", lambda *a, **k: _addrinfo("8.8.8.8"))
    respx.get("https://example.com/data.json").mock(
        return_value=httpx.Response(200, json={"x": 1}))
    assert await S.get_source_html("https://example.com/data.json") is None
