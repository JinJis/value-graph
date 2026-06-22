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

from app.http import fetch_json

# slug → {name, series (DBnomics provider/dataset/series), unit, region}
INDICATORS: dict[str, dict] = {
    "cpi": {"name": "US CPI (all items, SA)", "series": "BLS/cu/CUSR0000SA0", "unit": "index", "region": "US"},
    "core_cpi": {"name": "US Core CPI (ex food & energy, SA)", "series": "BLS/cu/CUSR0000SA0L1E",
                 "unit": "index", "region": "US"},
    "unemployment": {"name": "US Unemployment Rate", "series": "BLS/ln/LNS14000000", "unit": "%", "region": "US"},
    "nonfarm_payrolls": {"name": "US Nonfarm Payrolls", "series": "BLS/ce/CES0000000001",
                         "unit": "thousands", "region": "US"},
    "gdp_growth": {"name": "US Real GDP Growth (QoQ, annualized)", "series": "BEA/NIPA-T10101/A191RL-Q",
                   "unit": "%", "region": "US"},
    "pce_price": {"name": "US PCE Price Index", "series": "BEA/NIPA-T20804/DPCERG-M", "unit": "index", "region": "US"},
    "treasury_10y": {"name": "US 10Y Treasury Yield", "series": "OECD/KEI/IRLTLT01.USA.ST.M",
                     "unit": "%", "region": "US"},
    "euro_cpi": {"name": "Euro Area HICP (YoY)", "series": "Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA",
                 "unit": "%", "region": "EA"},
}


def _source_url(series: str) -> str:
    return f"https://db.nomics.world/{series}"


def list_indicators() -> list[dict]:
    return [{"slug": k, "name": v["name"], "unit": v["unit"], "region": v["region"]} for k, v in INDICATORS.items()]


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
