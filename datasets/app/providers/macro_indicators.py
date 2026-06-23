"""PH-DATA-4: economic-indicators DB via DBnomics (keyless, cloud-safe).

Provenance workflow for this source:
  · FETCH   — DBnomics series API (no key, no datacenter bot-wall, unlike FRED).
  · PROCESS — typed observations {date, value} per indicator.
  · STORE   — on-demand (time series; no store).
  · SHOW    — data card: the values + source "DBnomics" + `as_of` + a canonical
              `db.nomics.world/{provider}/{dataset}/{series}` page link (show the real source).

Each series id below was verified live against the DBnomics API (returns data).
"""

from __future__ import annotations

import asyncio

from app.http import fetch_json

# slug → {name, series (DBnomics provider/dataset/series), unit, region, group}
# `group` (하위요인) buckets the catalog so it browses by theme: 물가/고용/성장/금리.
INDICATORS: dict[str, dict] = {
    # 물가 (inflation)
    "cpi": {"name": "US CPI (all items, SA)", "series": "BLS/cu/CUSR0000SA0", "unit": "index", "region": "US", "group": "물가"},
    "core_cpi": {"name": "US Core CPI (ex food & energy, SA)", "series": "BLS/cu/CUSR0000SA0L1E",
                 "unit": "index", "region": "US", "group": "물가"},
    "pce_price": {"name": "US PCE Price Index", "series": "BEA/NIPA-T20804/DPCERG-M", "unit": "index", "region": "US", "group": "물가"},
    # 반도체 생산자물가 (PPI) — DRAM 현물가의 무료 대용(프록시). 월간 생산자물가, 현물 스팟 아님.
    "semiconductor_ppi": {"name": "US 반도체 생산자물가(PPI) — DRAM 현물가 아님(월간 프록시)",
                          "series": "BLS/pc/PCU334413334413", "unit": "index", "region": "US", "group": "물가"},
    "euro_cpi": {"name": "Euro Area HICP (YoY)", "series": "Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA",
                 "unit": "%", "region": "EA", "group": "물가"},
    # 고용 (labor)
    "unemployment": {"name": "US Unemployment Rate", "series": "BLS/ln/LNS14000000", "unit": "%", "region": "US", "group": "고용"},
    "nonfarm_payrolls": {"name": "US Nonfarm Payrolls", "series": "BLS/ce/CES0000000001",
                         "unit": "thousands", "region": "US", "group": "고용"},
    "labor_participation": {"name": "US Labor Force Participation Rate", "series": "BLS/ln/LNS11300000",
                            "unit": "%", "region": "US", "group": "고용"},
    # 성장 (growth)
    "gdp_growth": {"name": "US Real GDP Growth (QoQ, annualized)", "series": "BEA/NIPA-T10101/A191RL-Q",
                   "unit": "%", "region": "US", "group": "성장"},
    "industrial_production": {"name": "US Industrial Production Index", "series": "FED/G17/IP_B50001_S",
                             "unit": "index", "region": "US", "group": "성장"},
    # 금리 (rates)
    "treasury_10y": {"name": "US 10Y Treasury Yield", "series": "OECD/KEI/IRLTLT01.USA.ST.M",
                     "unit": "%", "region": "US", "group": "금리"},
    "treasury_3m": {"name": "US 3M Interbank Rate", "series": "OECD/KEI/IR3TIB01.USA.ST.M",
                    "unit": "%", "region": "US", "group": "금리"},
}


def _source_url(series: str) -> str:
    return f"https://db.nomics.world/{series}"


def list_indicators(region: str | None = None, group: str | None = None) -> list[dict]:
    """Browse the indicator catalog, optionally filtered by region (국가) or group (하위요인)."""
    out = []
    for k, v in INDICATORS.items():
        if region and v["region"] != region.upper():
            continue
        if group and v.get("group") != group:
            continue
        out.append({"slug": k, "name": v["name"], "unit": v["unit"], "region": v["region"], "group": v.get("group")})
    return out


def list_regions() -> list[str]:
    return sorted({v["region"] for v in INDICATORS.values()})


async def region_panel(region: str = "US", limit: int = 2) -> dict:
    """국가경제 panel: latest observation + prior + change for each indicator in a region
    (concurrent, best-effort — an indicator whose series fails upstream is dropped, never faked)."""
    region = (region or "US").upper()
    slugs = [k for k, v in INDICATORS.items() if v["region"] == region]
    fetched = await asyncio.gather(*[fetch_indicator(s, limit=max(2, limit)) for s in slugs])
    rows: list[dict] = []
    for slug, res in zip(slugs, fetched):
        obs = (res or {}).get("observations") or []
        if not obs:
            continue
        latest = obs[-1]
        prior = obs[-2] if len(obs) > 1 else None
        change = (latest["value"] - prior["value"]) if prior else None
        rows.append({"slug": slug, "name": res["name"], "unit": res.get("unit"), "group": INDICATORS[slug].get("group"),
                     "latest": latest["value"], "as_of": latest["date"],
                     "prior": prior["value"] if prior else None, "change": change,
                     "source_url": res.get("source_url")})
    return {"region": region, "source": "DBnomics", "indicators": rows}


async def fetch_indicator(slug: str, limit: int = 24) -> dict | None:
    """One indicator's recent observations + its DBnomics source link. None if unknown/failed."""
    meta = INDICATORS.get((slug or "").strip().lower())
    if not meta:
        return None
    series = meta["series"]
    try:
        data = await fetch_json("dbnomics", f"https://api.db.nomics.world/v22/series/{series}",
                                params={"observations": "1"})
    except Exception:  # noqa: BLE001 — upstream/network → graceful (None)
        return None
    docs = (data.get("series") or {}).get("docs") or [] if isinstance(data, dict) else []
    if not docs:
        return None
    doc = docs[0]
    obs: list[dict] = []
    for period, value in zip(doc.get("period") or [], doc.get("value") or []):
        try:
            obs.append({"date": period, "value": float(value)})
        except (TypeError, ValueError):
            continue  # "NA" / missing → dropped, never faked
    return {"slug": (slug or "").lower(), "name": meta["name"], "unit": meta.get("unit"),
            "region": meta.get("region"), "source": "DBnomics", "source_url": _source_url(series),
            "observations": obs[-limit:]}
