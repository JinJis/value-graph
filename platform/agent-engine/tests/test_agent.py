"""Agent Engine tests on the stub planner with a respx-mocked gateway."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from agentengine import agent as A
from agentengine import guardrails
from agentengine.config import settings
from agentengine.main import app

client = TestClient(app)

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
def test_guardrail_refuses_forecast_and_advice():
    assert guardrails.check("predict the AAPL price next month") is not None
    assert guardrails.check("should I buy TSLA?") is not None
    assert guardrails.check("what was AAPL revenue last year?") is None


def test_guardrail_covers_price_targets_and_directional_bets():
    for bad in ["what's the price target for NVDA", "forecast TSLA earnings",
                "will AAPL go up next week", "is MSFT worth buying"]:
        assert guardrails.check(bad) is not None, bad
    for ok in ["삼성전자 최근 실적", "show me AAPL filings", "what is the Fed funds rate"]:
        assert guardrails.check(ok) is None, ok


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
    assert "yahoo__prices" in res.answer and res.usage["steps"] == 1


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
