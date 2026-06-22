"""CE-HEALTH: probe each connector's upstream so the admin console shows, at a glance, which
data source is healthy/degraded/down — reachability, latency, and whether a required key is
configured (keys stay server-side; we only report presence, never the value).

Probes are LIGHTWEIGHT (a cheap GET with a short timeout) and avoid burning API quota — they
check that the host responds, not that an authenticated data call succeeds.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.config import settings

_UA = {"User-Agent": settings.sec_edgar_user_agent}

# id → probe spec. `key` = settings attr that must be set for the connector to actually work.
PROBES: list[dict] = [
    {"id": "sec_edgar", "name": "SEC EDGAR", "url": "https://www.sec.gov/", "key": None, "headers": _UA},
    {"id": "yahoo", "name": "Yahoo Finance",
     "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d", "key": None},
    {"id": "fred", "name": "FRED / DBnomics", "url": "https://api.db.nomics.world/v22/last-updates", "key": None},
    {"id": "opendart", "name": "OpenDART (KR)", "url": "https://opendart.fss.or.kr/", "key": "opendart_api_key"},
    {"id": "ecos", "name": "Bank of Korea ECOS", "url": "https://ecos.bok.or.kr/", "key": "ecos_api_key"},
    {"id": "google_news", "name": "Google News", "url": "https://news.google.com/rss", "key": None},
]


async def _probe(client: httpx.AsyncClient, spec: dict) -> dict:
    key_attr = spec.get("key")
    key_present = bool(getattr(settings, key_attr, "")) if key_attr else None
    t0 = time.monotonic()
    http_status: int | None = None
    reachable = False
    try:
        resp = await client.get(spec["url"], headers=spec.get("headers"), timeout=6.0, follow_redirects=True)
        http_status = resp.status_code
        reachable = True
    except Exception:  # noqa: BLE001 — any network error → unreachable (graceful)
        reachable = False
    latency_ms = round((time.monotonic() - t0) * 1000)
    # status: down (unreachable) · key-missing (reachable but required key absent) · degraded (4xx/5xx) · ok
    if not reachable:
        status = "down"
    elif key_attr and not key_present:
        status = "key-missing"
    elif http_status is not None and http_status >= 400:
        status = "degraded"
    else:
        status = "ok"
    return {"id": spec["id"], "name": spec["name"], "requires_key": bool(key_attr),
            "key_present": key_present, "reachable": reachable, "http_status": http_status,
            "latency_ms": latency_ms, "status": status}


async def probe_upstreams() -> dict:
    """Probe every upstream concurrently; return per-connector health for the admin console."""
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_probe(client, s) for s in PROBES])
    healthy = sum(1 for r in results if r["status"] == "ok")
    return {"upstreams": list(results), "healthy": healthy, "total": len(results)}
