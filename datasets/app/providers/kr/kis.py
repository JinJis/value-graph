"""CE-12: Korea Investment & Securities (KIS) — KR realtime rankings + investor flows.

The KR half competitors can't easily match: live volume rankings (활발 종목) and per-stock
investor flows (개인/외국인/기관 순매수 = 수급). OAuth token (app key/secret → 24h access token,
cached + rate-limit-aware; issuance is ~1/min). Keys stay server-side (KIS_APP_KEY/SECRET).
Descriptive market data — no advice/forecast.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.config import settings
from app.errors import bad_request, upstream_error
from app.http import fetch_json

# module-level token cache (token, expires_at_epoch); a lock so concurrent callers issue once.
_token_cache: dict = {"token": None, "exp": 0.0}
_token_lock = asyncio.Lock()


def _creds() -> tuple[str, str]:
    if not (settings.kis_app_key and settings.kis_app_secret):
        raise bad_request("KIS_APP_KEY / KIS_APP_SECRET are not configured.")
    return settings.kis_app_key, settings.kis_app_secret


async def _token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["exp"] - 60 > now:
        return _token_cache["token"]
    async with _token_lock:
        if _token_cache["token"] and _token_cache["exp"] - 60 > now:
            return _token_cache["token"]
        app_key, app_secret = _creds()
        try:
            async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
                resp = await client.post(
                    f"{settings.kis_domain}/oauth2/tokenP",
                    json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret})
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise upstream_error("kis", f"token request failed: {exc}")
        token = data.get("access_token")
        if not token:
            raise upstream_error("kis", f"no access_token ({data.get('msg1') or data})")
        # KIS tokens last ~24h; cache for 23h to be safe.
        _token_cache.update(token=token, exp=now + 23 * 3600)
        return token


async def _get(path: str, tr_id: str, params: dict) -> list:
    app_key, app_secret = _creds()
    headers = {"authorization": f"Bearer {await _token()}", "appkey": app_key,
               "appsecret": app_secret, "tr_id": tr_id, "custtype": "P"}
    data = await fetch_json("kis", f"{settings.kis_domain}{path}", params=params, headers=headers)
    if isinstance(data, dict) and str(data.get("rt_cd")) not in ("0", "None") and data.get("rt_cd") is not None:
        if str(data.get("rt_cd")) != "0":
            raise upstream_error("kis", str(data.get("msg1") or "KIS error")[:160])
    out = (data.get("output") if isinstance(data, dict) else None) or []
    return out if isinstance(out, list) else [out]


def _i(v):
    try:
        return int(str(v).replace(",", "")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def volume_rank(limit: int = 30) -> dict:
    """거래량 순위 (most-active KR stocks) — the KR 'movers' view (FMP movers are premium-gated)."""
    rows = await _get(
        "/uapi/domestic-stock/v1/quotations/volume-rank", "FHPST01710000",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171", "FID_INPUT_ISCD": "0000",
         "FID_DIV_CLS_CODE": "0", "FID_BLNG_CLS_CODE": "0", "FID_TRGT_CLS_CODE": "111111111",
         "FID_TRGT_EXLS_CLS_CODE": "0000000000", "FID_INPUT_PRICE_1": "", "FID_INPUT_PRICE_2": "",
         "FID_VOL_CNT": "", "FID_INPUT_DATE_1": ""})
    out = []
    for r in rows[:limit]:
        out.append({"rank": _i(r.get("data_rank")), "ticker": r.get("mksc_shrn_iscd"),
                    "name": r.get("hts_kor_isnm"), "price": _i(r.get("stck_prpr")),
                    "change_percent": _f(r.get("prdy_ctrt")), "volume": _i(r.get("acml_vol")),
                    "value": _i(r.get("acml_tr_pbmn"))})
    return {"market": "KR", "source": "한국투자증권 (KIS)", "ranking": "volume", "results": out}


async def investor_flow(ticker: str, limit: int = 10) -> dict:
    """투자자별 순매수 (개인/외국인/기관) for a KR stock — recent days; KR 수급 differentiator."""
    rows = await _get(
        "/uapi/domestic-stock/v1/quotations/inquire-investor", "FHKST01010900",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker})
    out = []
    for r in rows[:limit]:
        out.append({"date": r.get("stck_bsop_date"), "close": _i(r.get("stck_clpr")),
                    "individual_net": _i(r.get("prsn_ntby_qty")), "foreign_net": _i(r.get("frgn_ntby_qty")),
                    "institution_net": _i(r.get("orgn_ntby_qty"))})
    return {"market": "KR", "ticker": ticker, "source": "한국투자증권 (KIS)", "flows": out}
