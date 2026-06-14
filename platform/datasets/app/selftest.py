"""In-process endpoint self-test.

Drives a curated set of implemented endpoints through the real ASGI stack and
returns a structured pass / fail / skipped report. Exposed at GET /admin/selftest
so it can be run from /docs ("Try it out") to see what's working right now.

`skipped` = an upstream key or IP isn't available in this environment (e.g. DART
key missing, FRED IP-gated) — not a code failure.
"""

from __future__ import annotations

import time

from httpx import ASGITransport, AsyncClient

from app.config import settings

# Each check: name, method, path, optional json body. Only implemented endpoints.
_CHECKS: list[dict] = [
    # --- keyless (US: Yahoo/SEC, KR: Yahoo) ---
    {"name": "US prices (AAPL)", "method": "GET", "path": "/prices?ticker=AAPL&market=US&interval=day&start_date=2024-01-02&end_date=2024-01-05"},
    {"name": "US price snapshot (AAPL)", "method": "GET", "path": "/prices/snapshot?ticker=AAPL&market=US"},
    {"name": "KR prices (005930)", "method": "GET", "path": "/prices?ticker=005930&market=KR&interval=day&start_date=2024-05-02&end_date=2024-05-08"},
    {"name": "KR price snapshot (005930)", "method": "GET", "path": "/prices/snapshot?ticker=005930&market=KR"},
    {"name": "US company facts (AAPL)", "method": "GET", "path": "/company/facts?ticker=AAPL&market=US"},
    {"name": "US income statement (AAPL)", "method": "GET", "path": "/financials/income-statements?ticker=AAPL&market=US&period=annual&limit=1"},
    {"name": "US filings (AAPL)", "method": "GET", "path": "/filings?ticker=AAPL&market=US&limit=2"},
    {"name": "US metrics snapshot (AAPL)", "method": "GET", "path": "/financial-metrics/snapshot?ticker=AAPL&market=US"},
    {"name": "US news (AAPL)", "method": "GET", "path": "/news?ticker=AAPL&market=US&limit=2"},
    {"name": "US earnings (AAPL)", "method": "GET", "path": "/earnings?ticker=AAPL&market=US&limit=1"},
    {"name": "US insider trades (AAPL)", "method": "GET", "path": "/insider-trades?ticker=AAPL&market=US&limit=2"},
    {"name": "US 13F (Berkshire)", "method": "GET", "path": "/institutional-holdings?filer_cik=0001067983&limit=2"},
    {"name": "Screener (store)", "method": "POST", "path": "/financials/search/screener?market=US", "json": {"limit": 3, "filters": [{"field": "revenue", "operator": "gt", "value": 1}]}},
    # --- keyed (KR DART / ECOS, US FRED) — skipped if key/IP unavailable ---
    {"name": "KR company facts (DART)", "method": "GET", "path": "/company/facts?ticker=005930&market=KR"},
    {"name": "KR income statement (DART)", "method": "GET", "path": "/financials/income-statements?ticker=005930&market=KR&period=annual&limit=1"},
    {"name": "KR earnings (DART)", "method": "GET", "path": "/earnings?ticker=005930&market=KR&limit=1"},
    {"name": "KR insider trades (DART)", "method": "GET", "path": "/insider-trades?ticker=005930&market=KR&limit=2"},
    {"name": "KR macro / base rate (ECOS)", "method": "GET", "path": "/macro/interest-rates/snapshot?bank=BOK&market=KR"},
    {"name": "US macro / fed funds (FRED)", "method": "GET", "path": "/macro/interest-rates/snapshot?bank=FED&market=US"},
]

_SKIP_HINTS = ("not configured", "bot-verification", "gating", "challenge")


def _classify(status: int, body: str) -> tuple[str, str | None]:
    if status == 200:
        return "pass", None
    low = body.lower()
    if status in (400, 402, 503) and any(h in low for h in _SKIP_HINTS):
        return "skipped", "upstream key or IP not available in this environment"
    return "fail", body[:180]


def _headers() -> dict:
    keys = settings.accepted_api_keys
    if not settings.auth_disabled and keys:
        return {"X-API-KEY": next(iter(keys))}
    return {}


async def run_selftest(app) -> dict:
    transport = ASGITransport(app=app)
    headers = _headers()
    checks: list[dict] = []
    async with AsyncClient(transport=transport, base_url="http://selftest", headers=headers, timeout=90) as client:
        for chk in _CHECKS:
            started = time.monotonic()
            try:
                resp = await client.request(chk["method"], chk["path"], json=chk.get("json"))
                result, detail = _classify(resp.status_code, resp.text)
                status_code: int | None = resp.status_code
            except Exception as exc:  # transport / unexpected
                result, detail, status_code = "fail", str(exc)[:180], None
            checks.append(
                {
                    "name": chk["name"],
                    "endpoint": f"{chk['method']} {chk['path'].split('?')[0]}",
                    "result": result,
                    "http_status": status_code,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "detail": detail,
                }
            )
    summary = {
        "total": len(checks),
        "passed": sum(c["result"] == "pass" for c in checks),
        "failed": sum(c["result"] == "fail" for c in checks),
        "skipped": sum(c["result"] == "skipped" for c in checks),
    }
    return {"summary": summary, "checks": checks}
