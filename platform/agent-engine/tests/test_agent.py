"""Agent Engine tests on the stub planner with a respx-mocked gateway."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from agentengine import agent as A
from agentengine import guardrails
from agentengine import planner as P
from agentengine.config import settings
from agentengine.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _force_stub_backend(monkeypatch):
    """Keep the unit suite deterministic + key-free regardless of the dev .env
    (which may set AGENT_LLM_BACKEND=gemini)."""
    monkeypatch.setattr(settings, "llm_backend", "stub")
    P._build_planner.cache_clear()
    yield
    P._build_planner.cache_clear()

CATALOG = {"connectors": [
    {"id": "yahoo", "resources": [{
        "name": "prices", "method": "GET", "path": "/prices", "description": "EOD prices",
        "params": [{"name": "ticker", "required": True}, {"name": "interval", "required": True},
                   {"name": "start_date", "required": True}, {"name": "end_date", "required": True}, {"name": "market"}],
        "provenance": {"source": "Yahoo Finance"}}]},
    {"id": "sec_edgar", "resources": [{
        "name": "company_facts", "method": "GET", "path": "/company/facts", "description": "facts",
        "params": [{"name": "ticker"}, {"name": "market"}], "provenance": {"source": "SEC EDGAR"}}]},
    {"id": "rag", "resources": [{
        "name": "search", "method": "POST", "path": "/rag/search", "description": "semantic search",
        "params": [{"name": "query", "required": True}], "provenance": {"source": "Platform RAG"}}]},
]}


def _gw(monkeypatch):
    monkeypatch.setattr(settings, "gateway_url", "http://gw.test")


def _catalog():
    respx.get("http://gw.test/catalog").mock(return_value=httpx.Response(200, json=CATALOG))


# --- guardrails -----------------------------------------------------------
async def test_guardrail_refuses_forecast_and_advice():
    gd = guardrails.get_guardrailer()
    assert await gd.check("predict the AAPL price next month") is not None
    assert await gd.check("should I buy TSLA?") is not None
    assert await gd.check("what was AAPL revenue last year?") is None


async def test_guardrail_covers_price_targets_and_directional_bets():
    gd = guardrails.get_guardrailer()
    for bad in ["what's the price target for NVDA", "forecast TSLA earnings",
                "will AAPL go up next week", "is MSFT worth buying"]:
        assert await gd.check(bad) is not None, bad
    for ok in ["삼성전자 최근 실적", "show me AAPL filings", "what is the Fed funds rate"]:
        assert await gd.check(ok) is None, ok


def test_citations_extract_urls_from_nested_result():
    tool = {"name": "sec_edgar__filings", "source": "SEC EDGAR"}
    result = {"data": {"filings": [{"filing_url": "https://sec.gov/a"}, {"filing_url": "https://sec.gov/b"}]}}
    cites = A._citations(tool, result)
    urls = {c.url for c in cites}
    assert urls == {"https://sec.gov/a", "https://sec.gov/b"}
    assert all(c.source == "SEC EDGAR" for c in cites)


def test_citations_fallback_to_source_when_no_url():
    tool = {"name": "yahoo__prices", "source": "Yahoo Finance"}
    cites = A._citations(tool, {"data": {"ticker": "AAPL", "prices": []}})
    assert len(cites) == 1 and cites[0].url is None and cites[0].source == "Yahoo Finance"


def test_dedup_citations_collapses_repeats():
    from agentengine.models import Citation
    cites = [
        Citation(tool="opendart__income_statements", source="OpenDART (FSS)", url=None),
        Citation(tool="opendart__balance_sheets", source="OpenDART (FSS)", url=None),  # dup (src,url)
        Citation(tool="opendart__filings", source="OpenDART (FSS)", url="https://dart/x"),
    ]
    out = A.dedup_citations(cites)
    assert len(out) == 2  # the two same (source=None-url) collapse to one; the url'd one stays
    assert {(c.source, c.url) for c in out} == {("OpenDART (FSS)", None), ("OpenDART (FSS)", "https://dart/x")}


@respx.mock
async def test_fetch_tools_attaches_friendly_connector_name(monkeypatch):
    from agentengine.client import PlatformClient
    _gw(monkeypatch)
    catalog = {"connectors": [{"id": "opendart", "name": "OpenDART (KR)", "markets": ["KR"], "resources": [
        {"name": "income_statements", "method": "GET", "path": "/financials/income-statements",
         "description": "Income statements.", "params": [], "provenance": {"source": "OpenDART (FSS)"}}]}]}
    respx.get("http://gw.test/catalog").mock(return_value=httpx.Response(200, json=catalog))
    tools = await PlatformClient("k").fetch_tools()
    t = tools["opendart__income_statements"]
    # no raw id leaks into the human-facing fields
    assert t["connector_name"] == "OpenDART (KR)"
    assert t["friendly"] == "OpenDART (KR) · Income statements" and "__" not in t["friendly"]


# --- eval-driven fixes ----------------------------------------------------
async def test_guardrail_refuses_korean_forecast_and_advice():
    gd = guardrails.get_guardrailer()
    for bad in ["삼성전자 주가 오를까?", "지금 사야 할까요?", "AAPL 목표주가 알려줘",
                "엔비디아 전망 어때", "매수 추천 종목 알려줘", "테슬라 살까 팔까"]:
        assert await gd.check(bad) is not None, bad
    for ok in ["삼성전자 최근 실적", "AAPL 종가 흐름 알려줘", "한국은행 기준금리 얼마야",
               "엔비디아 공시 요약", "Fed 금리 추이"]:
        assert await gd.check(ok) is None, ok


def test_citations_use_per_hit_rag_provenance():
    # RAG answers must cite each passage's REAL source/url, not the connector's
    # generic label (the eval caught the agent citing "Platform RAG" instead).
    tool = {"name": "rag__search", "connector": "rag", "source": "Platform RAG (filings/news)"}
    result = {"data": {"hits": [
        {"text": "...", "provenance": {"source": "SEC EDGAR", "url": "https://sec.gov/aapl"}},
        {"text": "...", "provenance": {"source": "OpenDART (FSS)", "url": "https://dart/x"}},
    ]}}
    cites = A._citations(tool, result)
    assert {c.source for c in cites} == {"SEC EDGAR", "OpenDART (FSS)"}
    assert {c.url for c in cites} == {"https://sec.gov/aapl", "https://dart/x"}
    assert all(c.source != "Platform RAG (filings/news)" for c in cites)


# --- PH-4/U2: enriched citations for type-aware source-preview cards -----------
def test_freshness_buckets_from_as_of():
    from datetime import date

    from agentengine.freshness import compute_freshness

    today = date(2026, 6, 15)
    assert compute_freshness("2026-06-10", today) == "fresh"     # 5d
    assert compute_freshness("2026-05-01", today) == "aging"     # 45d
    assert compute_freshness("2025-01-01", today) == "stale"     # >1y
    assert compute_freshness(None, today) is None                # unknown, not a claim
    assert compute_freshness("not-a-date", today) is None


def test_rag_citation_is_enriched_for_preview_card():
    tool = {"name": "rag__search", "connector": "rag", "source": "Platform RAG"}
    result = {"data": {"hits": [
        {"text": "Apple sources chips from TSMC, a key supplier.",
         "provenance": {"source": "SEC EDGAR", "url": "https://sec.gov/aapl", "doc_type": "10-K",
                        "as_of": "2026-06-01", "ticker": "AAPL", "accession": "0000320193-26"}},
        {"text": "Apple beats on iPhone revenue - Reuters",
         "provenance": {"source": "Reuters", "url": "https://r/x", "doc_type": "news", "as_of": "2026-06-12"}},
    ]}}
    filing, news = A._citations(tool, result)
    assert filing.kind == "filing" and filing.doc_type == "10-K" and filing.ticker == "AAPL"
    assert filing.as_of == "2026-06-01" and filing.freshness in {"fresh", "aging", "stale"}
    assert "TSMC" in filing.snippet and filing.page == "0000320193-26"
    assert news.kind == "news" and news.source == "Reuters" and news.snippet.endswith("Reuters")


def test_datasets_citation_typed_metric_vs_data():
    price = A._citations({"name": "yahoo__prices", "source": "Yahoo Finance"}, {"data": {"prices": []}})
    filings = A._citations({"name": "sec_edgar__filings", "source": "SEC EDGAR"}, {"data": {"x": 1}})
    assert price[0].kind == "metric" and filings[0].kind == "data"


def test_news_citation_uses_publisher_headline_date():
    # /news must cite each article's publisher + headline + date, not "Google News"
    tool = {"name": "google_news__news", "connector": "google_news", "source": "Google News"}
    result = {"data": {"news": [
        {"ticker": "NVDA", "title": "Nvidia chips surge in overnight trading", "source": "Yahoo Finance",
         "date": "2026-06-15", "url": "https://news.google.com/x"},
        {"ticker": "NVDA", "title": "SpaceX growth lifts Nvidia", "source": "Barron's",
         "date": "2026-06-14", "url": "https://news.google.com/y"},
    ]}}
    cites = A._citations(tool, result)
    assert {c.source for c in cites} == {"Yahoo Finance", "Barron's"}  # publisher, not "Google News"
    assert all(c.kind == "news" and c.snippet and c.as_of for c in cites)
    assert cites[0].snippet.startswith("Nvidia chips") and cites[0].freshness == "fresh"


def test_financial_citation_gets_as_of_from_report_period():
    tool = {"name": "opendart__income_statements", "source": "OpenDART (FSS)"}
    result = {"data": {"statements": [
        {"report_period": "2025-12-31", "revenue": 1}, {"report_period": "2026-03-31", "revenue": 2},
    ]}}
    cite = A._citations(tool, result)[0]
    assert cite.as_of == "2026-03-31"  # latest report period becomes the figure's as-of
    assert cite.kind in {"metric", "data"} and cite.freshness is not None


def test_dedup_assigns_one_based_index():
    from agentengine.models import Citation
    out = A.dedup_citations([
        Citation(tool="t1", source="SEC EDGAR", url="https://a"),
        Citation(tool="t2", source="Reuters", url="https://b"),
        Citation(tool="t3", source="SEC EDGAR", url="https://a"),  # dup
    ])
    assert [c.index for c in out] == [1, 2]


@respx.mock
async def test_call_tool_forces_single_market_connector(monkeypatch):
    from agentengine.client import PlatformClient

    monkeypatch.setattr(settings, "gateway_url", "http://gw.test")
    route = respx.route(method="GET", url__regex=r"http://gw\.test/macro/interest-rates/snapshot").mock(
        return_value=httpx.Response(200, json={}, headers={"x-connector": "ecos"})
    )
    ecos = {"name": "ecos__interest_rates_snapshot", "connector": "ecos", "method": "GET",
            "path": "/macro/interest-rates/snapshot", "markets": ["KR"],
            "params": [{"name": "bank"}, {"name": "market"}]}
    # caller omitted market -> the KR-only connector must still route to KR (not FRED/US)
    await PlatformClient("k").call_tool(ecos, {"bank": "BOK"})
    assert "market=KR" in str(route.calls.last.request.url)


@respx.mock
async def test_call_tool_does_not_force_market_for_multi_market_tool(monkeypatch):
    from agentengine.client import PlatformClient

    monkeypatch.setattr(settings, "gateway_url", "http://gw.test")
    route = respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={}, headers={"x-connector": "yahoo"})
    )
    yahoo = {"name": "yahoo__prices", "connector": "yahoo", "method": "GET", "path": "/prices",
             "markets": ["US", "KR"], "params": [{"name": "ticker"}, {"name": "market"}]}
    await PlatformClient("k").call_tool(yahoo, {"ticker": "AAPL"})
    assert "market=" not in str(route.calls.last.request.url)  # multi-market -> caller decides


# --- agent loop -----------------------------------------------------------
@respx.mock
async def test_run_uses_tool_and_cites(monkeypatch):
    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"close": 185.6}]}, headers={"x-connector": "yahoo"})
    )
    res = await A.run_agent("What is AAPL's price?", "vgk_x")
    assert res.refused is False
    assert res.steps and res.steps[0].tool == "yahoo__prices" and res.steps[0].status == 200
    assert res.citations and res.citations[0].source == "Yahoo Finance"
    # PH-3: the raw tool id must NOT leak into the human-facing answer
    assert "yahoo__prices" not in res.answer and "`" not in res.answer
    assert res.usage["steps"] == 1


# --- PH-4c: inline [n] source anchors -----------------------------------------
def test_anchor_helpers():
    assert A.has_anchors("revenue grew [1].") is True
    assert A.has_anchors("no markers here") is False
    assert A.anchor_markers([1, 2, None, 3]) == "[1][2][3]"  # skips falsy index


@respx.mock
async def test_run_agent_anchors_answer_when_model_omits(monkeypatch):
    # stub summary carries no [n]; with one citation the answer must end source-anchored
    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"close": 185.6}]}, headers={"x-connector": "yahoo"})
    )
    res = await A.run_agent("What is AAPL's price?", "vgk_x")
    assert A.has_anchors(res.answer) and res.answer.rstrip().endswith("[1]")
    assert res.citations[0].index == 1  # anchor matches the citation index


@respx.mock
async def test_chat_stream_emits_trailing_anchor(monkeypatch):
    from agentengine.chat import stream_chat

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"close": 185.6}]}, headers={"x-connector": "yahoo"})
    )
    events = [e async for e in stream_chat([{"role": "user", "content": "What is AAPL price?"}], "vgk_x")]
    prose = "".join(e["text"] for e in events if e["type"] == "token")
    assert A.has_anchors(prose) and "[1]" in prose
    cite = next(e for e in events if e["type"] == "citation")
    assert cite["index"] == 1


@respx.mock
async def test_run_refuses_forecast(monkeypatch):
    _gw(monkeypatch)
    res = await A.run_agent("Will AAPL go up next week?", "vgk_x")
    assert res.refused is True and res.steps == []


@respx.mock
async def test_run_routes_to_rag(monkeypatch):
    _gw(monkeypatch)
    _catalog()
    respx.route(method="POST", url__regex=r"http://gw\.test/rag/search").mock(
        return_value=httpx.Response(200, json={"hits": [{"text": "...", "provenance": {"source": "SEC EDGAR", "url": "https://sec.gov/x"}}]}, headers={"x-connector": "rag"})
    )
    res = await A.run_agent("What does Apple disclose about supplier risk?", "vgk_x")
    assert res.steps[0].tool == "rag__search" and res.steps[0].status == 200
    assert any(c.url == "https://sec.gov/x" for c in res.citations)


@respx.mock
async def test_run_respects_allowed_tools(monkeypatch):
    from agentengine.models import AgentSpec

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/company/facts").mock(
        return_value=httpx.Response(200, json={"company_facts": {"ticker": "AAPL"}}, headers={"x-connector": "sec_edgar"})
    )
    # only company_facts allowed -> a price question still falls back to it
    res = await A.run_agent("Tell me about AAPL price", "vgk_x", AgentSpec(allowed_tools=["sec_edgar__company_facts"]))
    assert res.steps[0].tool == "sec_edgar__company_facts"


# --- endpoints ------------------------------------------------------------
@respx.mock
def test_endpoint_run(monkeypatch):
    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": []}, headers={"x-connector": "yahoo"})
    )
    r = client.post("/agent/run", json={"task": "AAPL price?"}, headers={"X-API-KEY": "vgk_x"}).json()
    assert r["steps"][0]["tool"] == "yahoo__prices" and r["citations"]


def test_info_and_compile():
    assert client.get("/agent/info").json()["llm_backend"] == "stub"
    spec = client.post("/agent/compile", json={"description": "Summarize a ticker's filings"}).json()
    assert spec["system"] == "Summarize a ticker's filings"


# --- streaming chat -------------------------------------------------------
@respx.mock
async def test_chat_stream_uses_tool_and_cites(monkeypatch):
    from agentengine.chat import stream_chat

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"close": 185.6}]}, headers={"x-connector": "yahoo"})
    )
    events = [e async for e in stream_chat([{"role": "user", "content": "What is AAPL price?"}], "vgk_x")]
    types = [e["type"] for e in events]
    assert "tool" in types and "tool_result" in types and "citation" in types
    assert any(e["type"] == "token" for e in events)
    assert events[-1]["type"] == "done" and events[-1]["refused"] is False
    tool_ev = next(e for e in events if e["type"] == "tool")
    assert tool_ev["name"] == "yahoo__prices"
    cite = next(e for e in events if e["type"] == "citation")
    assert cite["source"] == "Yahoo Finance"


@respx.mock
async def test_chat_stream_guardrail_refuses(monkeypatch):
    from agentengine.chat import stream_chat

    _gw(monkeypatch)
    events = [e async for e in stream_chat([{"role": "user", "content": "should I buy AAPL?"}], "vgk_x")]
    assert all(e["type"] != "tool" for e in events)
    assert events[-1]["type"] == "done" and events[-1]["refused"] is True
    assert any(e["type"] == "token" for e in events)


@respx.mock
async def test_chat_stream_platform_unavailable(monkeypatch):
    from agentengine.chat import stream_chat

    _gw(monkeypatch)
    respx.get("http://gw.test/catalog").mock(return_value=httpx.Response(503))
    events = [e async for e in stream_chat([{"role": "user", "content": "AAPL price?"}], "vgk_x")]
    assert all(e["type"] != "tool" for e in events)  # no tool could be called
    assert any(e["type"] == "token" for e in events)  # but the user still gets a message
    assert events[-1] == {"type": "done", "citations": [], "refused": False}


@respx.mock
async def test_chat_stream_uses_last_user_turn(monkeypatch):
    # multi-turn: the planner should route on the LATEST user message, not the first
    from agentengine.chat import stream_chat

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": []}, headers={"x-connector": "yahoo"})
    )
    messages = [
        {"role": "user", "content": "tell me about Apple filings"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "what is AAPL price?"},
    ]
    events = [e async for e in stream_chat(messages, "vgk_x")]
    tool_ev = next(e for e in events if e["type"] == "tool")
    assert tool_ev["name"] == "yahoo__prices"  # routed on the price question, not filings


@respx.mock
async def test_chat_stream_respects_allowed_tools(monkeypatch):
    from agentengine.chat import stream_chat
    from agentengine.models import AgentSpec

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/company/facts").mock(
        return_value=httpx.Response(200, json={"company_facts": {}}, headers={"x-connector": "sec_edgar"})
    )
    spec = AgentSpec(allowed_tools=["sec_edgar__company_facts"])
    events = [e async for e in stream_chat([{"role": "user", "content": "AAPL price?"}], "vgk_x", spec)]
    tool_ev = next(e for e in events if e["type"] == "tool")
    assert tool_ev["name"] == "sec_edgar__company_facts"  # price tool filtered out


# --- stub planner robustness (no bad tool calls) --------------------------
def test_resolve_ticker_names_codes_and_acronyms():
    from agentengine.planner import resolve_ticker

    assert resolve_ticker("삼성전자 최근 실적") == "005930"   # KR name -> code
    assert resolve_ticker("엔비디아 공급망") == "NVDA"          # KR alias for a US name
    assert resolve_ticker("AAPL 최근 주가") == "AAPL"           # explicit symbol
    assert resolve_ticker("005930 공시") == "005930"            # explicit KR code
    assert resolve_ticker("what is EPS and PER?") is None       # acronyms are not tickers
    assert resolve_ticker("artificial intelligence trends") is None  # 'intel' must not fire


_TOOLS = {
    "yahoo__prices": {"name": "yahoo__prices", "markets": ["US", "KR"], "params": [
        {"name": "ticker"}, {"name": "interval", "required": True}, {"name": "start_date", "required": True},
        {"name": "end_date", "required": True}, {"name": "market"}]},
    "sec_edgar__company_facts": {"name": "sec_edgar__company_facts", "markets": ["US"], "params": [
        {"name": "ticker"}, {"name": "market"}]},
    "opendart__income_statements": {"name": "opendart__income_statements", "markets": ["KR"], "params": [
        {"name": "ticker"}, {"name": "period", "required": True}, {"name": "market"}]},
    "fred__interest_rates": {"name": "fred__interest_rates", "markets": ["US"], "params": [
        {"name": "bank", "required": True}, {"name": "market"}]},
    "rag__search": {"name": "rag__search", "markets": ["US", "KR"], "params": [{"name": "query", "required": True}]},
}


async def _decide(task):
    from agentengine.planner import StubPlanner

    return await StubPlanner().plan(task, _TOOLS, [], None)


async def test_planner_routes_kr_name_to_kr_connector_with_code():
    d = await _decide("삼성전자 최근 실적")
    assert d.tool == "opendart__income_statements"  # KR market -> DART, not SEC
    assert d.args["ticker"] == "005930" and d.args["market"] == "KR" and d.args["period"] == "annual"


async def test_planner_price_question_fills_required_args():
    d = await _decide("AAPL 최근 주가 흐름")
    assert d.tool == "yahoo__prices"
    assert d.args["ticker"] == "AAPL" and d.args["interval"] and d.args["start_date"] and d.args["end_date"]


async def test_planner_macro_needs_no_ticker():
    d = await _decide("Fed 기준금리 추이")
    assert d.tool == "fred__interest_rates" and d.args["bank"] == "FED" and d.args["market"] == "US"
    assert "ticker" not in d.args


async def test_planner_skips_ticker_tools_when_no_ticker_resolvable():
    # no company/ticker, no macro/search intent -> finalize with guidance, never a 400 call
    d = await _decide("주식 시장 어때?")
    assert d.tool is None and d.final and "티커" in d.final


async def test_planner_never_calls_us_tool_for_kr_code():
    d = await _decide("005930 재무제표")
    assert d.tool == "opendart__income_statements"  # market-filtered to KR
    assert d.args["market"] == "KR"


async def test_planner_resolves_ticker_from_prior_turn():
    # follow-up "그럼 주가는?" has no ticker — it must inherit 삼성전자 from turn 1
    from agentengine.planner import StubPlanner

    conversation = [
        {"role": "user", "content": "삼성전자 최근 실적 알려줘"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "그럼 최근 주가는?"},
    ]
    d = await StubPlanner().plan("그럼 최근 주가는?", _TOOLS, [], None, conversation=conversation)
    assert d.tool == "yahoo__prices" and d.args["ticker"] == "005930" and d.args["market"] == "KR"


@respx.mock
async def test_chat_stream_multi_turn_inherits_context(monkeypatch):
    from agentengine.chat import stream_chat

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": []}, headers={"x-connector": "yahoo"})
    )
    messages = [
        {"role": "user", "content": "Apple 최근 실적 알려줘"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "그럼 주가 흐름은?"},  # no ticker -> inherits Apple/AAPL
    ]
    events = [e async for e in stream_chat(messages, "vgk_x")]
    tool_ev = next(e for e in events if e["type"] == "tool")
    assert tool_ev["name"] == "yahoo__prices" and tool_ev["args"].get("ticker") == "AAPL"


def test_chat_chunks_reconstruct_text():
    from agentengine.chat import _chunks

    assert "".join(_chunks("the quick brown fox jumps over the lazy dog", size=3)) == "the quick brown fox jumps over the lazy dog"
    assert _chunks("") == [""]  # empty stays a single chunk, never crashes


# --- F1: agent spec (connector filter / backend / system) -----------------
def test_filter_tools_by_connector_or_tool_name():
    tools = {"yahoo__prices": {}, "sec_edgar__company_facts": {}, "sec_edgar__filings": {}, "rag__search": {}}
    # connector id selects all of its tools
    assert set(A.filter_tools(tools, ["sec_edgar"])) == {"sec_edgar__company_facts", "sec_edgar__filings"}
    # full tool name selects exactly one; entries can mix granularity
    assert set(A.filter_tools(tools, ["yahoo__prices", "rag"])) == {"yahoo__prices", "rag__search"}
    # empty/None = no restriction
    assert A.filter_tools(tools, None) == tools
    assert A.filter_tools(tools, []) == tools


@respx.mock
async def test_run_with_data_source_subset_restricts_to_connector(monkeypatch):
    from agentengine.models import AgentSpec

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/company/facts").mock(
        return_value=httpx.Response(200, json={"company_facts": {"ticker": "AAPL"}}, headers={"x-connector": "sec_edgar"})
    )
    # a price question, but the agent's data sources are SEC only -> never calls yahoo
    res = await A.run_agent("AAPL price?", "vgk_x", AgentSpec(allowed_tools=["sec_edgar"]))
    assert res.steps and res.steps[0].tool.startswith("sec_edgar__")
    assert all(not s.tool.startswith("yahoo__") for s in res.steps)


def test_get_planner_backend_override_is_isolated():
    from agentengine.planner import GeminiPlanner, StubPlanner, get_planner

    assert isinstance(get_planner("stub"), StubPlanner)
    assert isinstance(get_planner(None), StubPlanner)  # falls back to settings (stub in tests)
    # an unknown backend is rejected loudly
    import pytest

    with pytest.raises(ValueError):
        get_planner("does-not-exist")


async def test_stub_planner_accepts_system_arg():
    # the system prompt is threaded through; the stub ignores it but must not error
    from agentengine.planner import StubPlanner

    d = await StubPlanner().plan("AAPL price?", {"yahoo__prices": {"name": "yahoo__prices", "params": []}}, [], "Be concise.")
    assert d.tool == "yahoo__prices"


def test_chat_endpoint_sse(monkeypatch):
    import respx as _respx

    with _respx.mock:
        _gw(monkeypatch)
        _catalog()
        _respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
            return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": []}, headers={"x-connector": "yahoo"})
        )
        r = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "AAPL price?"}]}, headers={"X-API-KEY": "vgk_x"})
        assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
        assert '"type": "tool"' in r.text and '"type": "done"' in r.text


async def test_gemini_guardrailer_violates(monkeypatch):
    pytest.importorskip("google.genai")  # needs the `gemini` extra; skip on the dep-free dev run
    from unittest.mock import MagicMock
    from agentengine.guardrails import GeminiGuardrailer
    import google.genai

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"violates": true}'
    mock_client.models.generate_content.return_value = mock_response

    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: mock_client)

    g = GeminiGuardrailer("model-id")
    refusal = await g.check("should I buy Apple stock?")
    assert refusal is not None

    mock_response.text = '{"violates": false}'
    refusal = await g.check("what is Apple's revenue?")
    assert refusal is None


def test_get_guardrailer_factory(monkeypatch):
    pytest.importorskip("google.genai")  # needs the `gemini` extra; skip on the dep-free dev run
    from unittest.mock import MagicMock
    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MagicMock())

    from agentengine.guardrails import GeminiGuardrailer, StubGuardrailer, get_guardrailer

    assert isinstance(get_guardrailer("stub"), StubGuardrailer)
    assert isinstance(get_guardrailer("gemini"), GeminiGuardrailer)


def test_to_gemini_contents_mapping():
    pytest.importorskip("google.genai")  # needs the `gemini` extra; skip on the dep-free dev run
    from agentengine.planner import _to_gemini_contents, Decision
    from google.genai import types

    conversation = [
        {"role": "user", "content": "What is AAPL price?"},
        {"role": "assistant", "content": "Let me look up the price."}
    ]
    history = [
        (Decision(tool="yahoo__prices", args={"ticker": "AAPL"}, thought_signature=b"sig_data"), {"status": 200, "data": {"close": 180.5}})
    ]
    task = "Is it higher than last week?"

    contents = _to_gemini_contents(conversation, history, task)
    assert len(contents) == 4
    # Turn 0: User message "What is AAPL price?"
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "What is AAPL price?"
    # Turn 1: Assistant message "Let me look up the price."
    assert contents[1].role == "model"
    assert contents[1].parts[0].text == "Let me look up the price."
    # Turn 2: Model function call + thought signature
    assert contents[2].role == "model"
    assert contents[2].parts[0].function_call.name == "yahoo__prices"
    assert contents[2].parts[0].function_call.args == {"ticker": "AAPL"}
    assert contents[2].parts[0].thought_signature == b"sig_data"
    # Turn 3: Tool response
    assert contents[3].role == "tool"
    assert contents[3].parts[0].function_response.name == "yahoo__prices"
    assert contents[3].parts[0].function_response.response == {"close": 180.5}


def test_schema_maps_param_descriptions():
    from agentengine.planner import _schema

    tool = {
        "name": "test_tool",
        "params": [
            {"name": "ticker", "required": True, "description": "Stock symbol (e.g. AAPL)"},
            {"name": "interval", "enum": ["day", "week"]}
        ]
    }
    schema = _schema(tool)
    assert schema["properties"]["ticker"]["description"] == "Stock symbol (e.g. AAPL)"
    assert "description" not in schema["properties"]["interval"]


