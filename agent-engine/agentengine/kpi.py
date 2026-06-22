"""PH-DATA-5 / PH-9: KPI extraction from the filing-text RAG corpus.

Valley AI exposes a "KPI/실적" panel; our differentiation is that **every KPI is a
reported figure cited to (and highlighted in) the real filing passage it came from** —
never a forecast, never fabricated.

Provenance workflow for this derived view:
  · FETCH   — `rag__search` over the company's ingested filing passages (the PROV3e
              corpus) through the gateway, so entitlement + metering still apply.
  · PROCESS — Gemini reads the passages and extracts only REPORTED operating KPIs
              (no forecasts / targets — guardrail), each tied to the passage index.
  · STORE   — none (derived on demand from the corpus).
  · SHOW    — a `kpi` table artifact + one Citation per KPI, each carrying the source
              passage snippet and an `/evidence` text-highlight URL (the real line).

No LLM key (stub backend) → we DON'T fabricate KPIs; we return the candidate filing
passages as citations and say extraction needs the gemini backend (honesty over fake).
"""

from __future__ import annotations

import json
import logging

from agentengine.evidence import rag_evidence_url
from agentengine.models import Artifact, Citation
from agentengine.routing import _market_of, resolve_ticker

log = logging.getLogger(__name__)

# Steer retrieval at the operating-KPI passages (income, segments, units, margins) —
# this is a retrieval query, not reasoning; the extraction itself is the LLM's job.
_KPI_QUERY = (
    "key performance metrics: net sales revenue, operating income, net income, gross margin, "
    "operating margin, segment results, units sold, subscribers, backlog, EPS"
)
_DEFAULT_TOP_K = 8
_MAX_KPIS = 12

# Gemini structured-output schema for the extraction step.
_EXTRACT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "kpis": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING", "description": "KPI label as reported (e.g. 'Total net sales')."},
                    "value": {"type": "STRING", "description": "Reported value as written (e.g. '391,035')."},
                    "unit": {"type": "STRING", "description": "Unit (e.g. '$M', '%', 'units'). Empty if none."},
                    "period": {"type": "STRING", "description": "Reporting period (e.g. 'FY2024'). Empty if unclear."},
                    "passage_index": {"type": "INTEGER", "description": "0-based index of the source passage."},
                },
                "required": ["name", "value", "passage_index"],
            },
        }
    },
    "required": ["kpis"],
}

_EXTRACT_SYSTEM = (
    "You extract REPORTED key performance indicators from public-company filing passages. "
    "Rules: (1) Only figures explicitly stated in a passage — never estimate, forecast, "
    "annualize, or compute new numbers. (2) Each KPI MUST set passage_index to the passage "
    "it was read from. (3) Prefer headline operating KPIs (revenue/net sales, operating & net "
    "income, margins, segment/product revenue, units/subscribers, EPS). (4) Keep the value "
    "exactly as written. (5) Skip anything you cannot tie to a specific passage."
)


async def _gemini_extract(model: str, ticker: str, passages: list[dict]) -> list[dict]:
    """Real path: one Gemini structured call over the retrieved passages. Same provider /
    service / auth as the planner; returns [] on any SDK/parse error (caller degrades)."""
    import asyncio

    from google import genai
    from google.genai import types

    numbered = "\n\n".join(f"[passage {i}]\n{p['text'][:1500]}" for i, p in enumerate(passages))
    user = (f"Company: {ticker}\nExtract the reported KPIs from these filing passages "
            f"(use passage_index to cite each):\n\n{numbered}")
    config = types.GenerateContentConfig(
        system_instruction=_EXTRACT_SYSTEM, temperature=0.1,
        response_mime_type="application/json", response_schema=_EXTRACT_SCHEMA,
    )
    try:
        client = genai.Client()
        resp = await asyncio.to_thread(
            client.models.generate_content, model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=user)])], config=config)
        payload = json.loads(resp.text or "{}")
        return payload.get("kpis") or []
    except Exception as exc:  # noqa: BLE001 — degrade to no-extraction, never crash the endpoint
        log.warning("kpi: gemini extraction failed for %s: %s", ticker, exc)
        return []


def _passage_citation(tool_name: str, p: dict, ticker: str, snippet_len: int = 300) -> Citation:
    text = p.get("text") or ""
    return Citation(
        tool=tool_name, source=p.get("source"), url=p.get("url"), kind="filing",
        as_of=p.get("as_of"), snippet=text[:snippet_len] or None, ticker=ticker,
        page=p.get("section") or p.get("accession"),
        evidence_image_url=rag_evidence_url(p.get("market"), p.get("accession"), text),
    )


async def extract_kpis(client, tools: dict, ticker: str, market: str | None,
                       *, backend: str, model: str, top_k: int | None = None) -> dict:
    """Fetch filing passages → (gemini) extract reported KPIs → return them with per-KPI
    evidence + a pinnable `kpi` table artifact. Honest when the corpus is empty or no key."""
    ticker = (ticker or "").strip()
    market = (market or _market_of(ticker) or "US").upper()
    top_k = top_k or _DEFAULT_TOP_K

    rag = next((t for t in tools.values()
                if t.get("connector") == "rag" and t["name"].endswith("__search")), None)
    if rag is None:
        return {"ticker": ticker, "market": market, "kpis": [], "citations": [], "artifact": None,
                "note": "Document search (RAG) is not activated for this project."}

    res = await client.call_tool(rag, {"query": _KPI_QUERY, "ticker": ticker, "market": market, "top_k": top_k})
    hits = (res.get("data") or {}).get("hits") or [] if isinstance(res.get("data"), dict) else []
    # Only filing passages (they carry an accession → highlightable in the cached PDF).
    passages: list[dict] = []
    for h in hits:
        prov = (h or {}).get("provenance") or {}
        if prov.get("accession") and (h or {}).get("text"):
            passages.append({"text": h["text"], "accession": prov["accession"],
                             "market": prov.get("market") or market, "section": prov.get("section"),
                             "url": prov.get("url"), "source": prov.get("source"), "as_of": prov.get("as_of")})
    if not passages:
        return {"ticker": ticker, "market": market, "kpis": [], "citations": [], "artifact": None,
                "note": "No filing-text passages are indexed for this company yet."}

    raw = await _gemini_extract(model, ticker, passages) if backend == "gemini" else []

    kpis, citations = [], []
    for k in raw[:_MAX_KPIS]:
        try:
            idx = int(k.get("passage_index"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(passages)) or not k.get("name") or k.get("value") in (None, ""):
            continue  # must tie to a real passage + carry a value (no unsourced KPI)
        p = passages[idx]
        cite = _passage_citation(rag["name"], p, ticker)
        cite.snippet = (str(k["name"]) + ": " + str(k["value"])
                        + (f" {k['unit']}" if k.get("unit") else ""))[:300]
        cite.table = [[str(k["name"]), str(k["value"])]]
        cite.used = True
        unit = f" {k['unit']}" if k.get("unit") else ""
        kpis.append({"name": str(k["name"]), "value": str(k["value"]), "unit": k.get("unit") or "",
                     "period": k.get("period") or "", "source": p.get("source"),
                     "accession": p.get("accession"), "url": p.get("url"),
                     "snippet": (p.get("text") or "")[:300],
                     "evidence_image_url": cite.evidence_image_url})
        citations.append(cite)

    if not kpis:  # no extraction (stub/no-key or model returned nothing) → still show the sourced passages
        citations = [_passage_citation(rag["name"], p, ticker) for p in passages[:5]]
        note = ("Sourced filing passages returned; KPI extraction needs the gemini backend."
                if backend != "gemini" else "No reported KPIs could be extracted from the indexed passages.")
        return {"ticker": ticker, "market": market, "kpis": [], "citations": [c.model_dump() for c in citations],
                "artifact": None, "note": note}

    src = next((c.source for c in citations if c.source), None)
    as_of = max((c.as_of for c in citations if c.as_of), default=None)
    table = [["지표", "값", "기간"]] + [
        [k["name"], (k["value"] + (f" {k['unit']}" if k["unit"] else "")), k["period"]] for k in kpis]
    artifact = Artifact(kind="kpi", title=f"{ticker} — 핵심 지표 (KPI)", table=table,
                        source=src, as_of=as_of, ticker=ticker)
    return {"ticker": ticker, "market": market, "kpis": kpis,
            "citations": [c.model_dump() for c in citations], "artifact": artifact.model_dump()}
