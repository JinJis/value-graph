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


def test_filing_link_canonical_per_market():
    # KR → DART rcpNo viewer (deterministic); US → SEC index page (needs CIK)
    assert A._filing_link("KR", "20260605000073") == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260605000073"
    assert A._filing_link("US", "0000320193-25-000079", "320193") == \
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm"
    assert A._filing_link("US", "0000320193-25-000079", None) is None
    assert A._filing_link("US", None) is None


def test_citations_metrics_show_real_figures_and_canonical_link():
    # a derived-metrics result → ONE evidence card with the actual figures + a table +
    # the canonical filing link built from accession (not a directory listing).
    tool = {"name": "datasets_store__metrics_history", "source": "SEC EDGAR", "connector": "datasets_store"}
    data = {"market": "US", "ticker": "AAPL", "metrics": [
        {"report_period": "2025-12-31", "gross_margin": 0.46, "net_margin": 0.25,
         "accession_number": "0000320193-25-000079", "cik": "320193"},
        {"report_period": "2024-12-31", "gross_margin": 0.44, "net_margin": 0.23,
         "accession_number": "0000320193-24-000123", "cik": "320193"}]}
    cites = A._citations(tool, {"data": data})
    assert len(cites) == 1
    c = cites[0]
    assert c.url == "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm"
    assert "46.0%" in (c.snippet or "")          # the real figure, not "지표 계산값"
    assert c.table and c.table[0][0] == "기간"     # extracted table, header first
    assert "2025-12-31" in c.table[1]
    assert c.page == "0000320193-25-000079"


def test_mark_evidence_only_cited_or_artifact_backing():
    from agentengine.models import Artifact
    cites = [A.Citation(tool="t1", source="A", url="u1", index=1, snippet="x"),
             A.Citation(tool="t2", source="B", url="u2", index=2, snippet="y"),
             A.Citation(tool="t3", source="C", url="u3", index=3)]
    arts = [Artifact(kind="timeseries", title="z", tool="t3")]
    A.mark_evidence(cites, "핵심 수치는 이렇습니다 [1].", arts)
    used = {c.index for c in cites if c.used}
    assert used == {1, 3}            # [1] cited + t3 backs an artifact; t2 consulted-only


def test_mark_evidence_fallback_when_no_inline_anchors():
    cites = [A.Citation(tool="t1", source="A", url="u1", index=1, snippet="real"),
             A.Citation(tool="t2", source="B", index=2)]  # bare label, no data
    A.mark_evidence(cites, "근거를 정리했습니다.", [])
    assert cites[0].used and not cites[1].used   # data-bearing is evidence; bare label is not


def test_citations_prices_and_generic_show_real_values():
    # prices → a date/close table + latest-close snippet (no filing link, that's fine)
    tool = {"name": "yahoo__prices", "source": "Yahoo Finance", "connector": "yahoo"}
    data = {"ticker": "AAPL", "prices": [
        {"time": "2026-06-12T00:00:00", "close": 210.5}, {"time": "2026-06-13T00:00:00", "close": 213.0}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.table[0] == ["날짜", "종가"] and c.table[1][0] == "2026-06-13"  # newest first
    assert "213" in (c.snippet or "")
    # generic tabular result → a table of its real values (scales to new data sources)
    tool2 = {"name": "datasets_store__insider", "source": "SEC EDGAR", "connector": "datasets_store"}
    data2 = {"trades": [{"insider": "CEO", "shares": 1000, "filing_url": "https://x"}]}
    c2 = A._citations(tool2, {"data": data2})[0]
    assert c2.table is not None and c2.url == "https://x"


def test_evidence_url_attached_for_us_as_reported_filing():
    # an as-reported (US) result → the citation carries an /evidence URL for the headline
    # figure (PH-PROV2); the frontend fetches the highlighted screenshot lazily.
    tool = {"name": "sec_edgar__as_reported", "source": "SEC EDGAR", "connector": "sec_edgar"}
    data = {"ticker": "AAPL", "periods": [{"report_period": "2024-09-28", "line_items": [
        {"concept": "Revenues", "value": 391035000000.0, "accession_number": "0000320193-24-000123", "cik": "320193"},
        {"concept": "Assets", "value": 352755000000.0, "accession_number": "0000320193-24-000123", "cik": "320193"}]}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.evidence_image_url is not None
    assert "/evidence?" in c.evidence_image_url
    assert "concept=Revenues" in c.evidence_image_url and "accession=0000320193-24-000123" in c.evidence_image_url
    assert "report_period=2024-09-28" in c.evidence_image_url


def test_evidence_url_for_income_statements_uses_candidate_concepts():
    # the common income_statements tool uses OUR normalized fields → reverse-map to candidate
    # us-gaap concepts so the answer's revenue figure still gets an evidence link (PH-PROV2b).
    tool = {"name": "sec_edgar__income_statements", "source": "SEC EDGAR", "connector": "sec_edgar"}
    data = {"income_statements": [
        {"revenue": 391035000000.0, "net_income": 93736000000.0, "report_period": "2024-09-28",
         "accession_number": "0000320193-24-000123"},
        {"revenue": 383285000000.0, "report_period": "2023-09-30", "accession_number": "0000320193-23-000106"}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.evidence_image_url and "/evidence?" in c.evidence_image_url
    assert "accession=0000320193-24-000123" in c.evidence_image_url      # newest period
    assert "report_period=2024-09-28" in c.evidence_image_url
    # revenue maps to a candidate list (try each tag in order at lookup time)
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in c.evidence_image_url
    assert "Revenues" in c.evidence_image_url


def test_evidence_url_for_kr_dart_statements():
    # PH-PROV2d: KR income_statements (OpenDART) → an /evidence URL anchored on the field
    # name (the DART matcher resolves it to the account label); market=KR, no us-gaap concept.
    tool = {"name": "opendart__income_statements", "source": "OpenDART (FSS)", "connector": "opendart"}
    data = {"income_statements": [
        {"revenue": 300870903000000.0, "net_income": 34451351000000.0, "report_period": "2024-12-31",
         "accession_number": "20250311000736"},
        {"revenue": 258935494000000.0, "report_period": "2023-12-31", "accession_number": "20240312000736"}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.evidence_image_url and "/evidence?" in c.evidence_image_url
    assert "market=KR" in c.evidence_image_url
    assert "concept=revenue" in c.evidence_image_url          # field name, not a us-gaap tag
    assert "accession=20250311000736" in c.evidence_image_url  # newest period
    assert "report_period=2024-12-31" in c.evidence_image_url


def test_corporate_actions_citation_is_a_dividend_data_card():
    # PH-DATA-3: dividends/splits (Yahoo, no document) → data-card evidence (real values + source).
    tool = {"name": "yahoo__corporate_actions", "source": "Yahoo Finance", "connector": "yahoo"}
    data = {"ticker": "AAPL", "currency": "USD",
            "dividends": [{"ex_date": "2026-02-07", "amount": 0.25}, {"ex_date": "2025-11-07", "amount": 0.25}],
            "splits": [{"date": "2020-08-31", "ratio": "4:1"}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.table and c.table[0] == ["배당락일", "배당금"]
    assert c.table[1][0] == "2026-02-07" and "배당" in (c.snippet or "")
    assert c.evidence_image_url is None  # no document → data card only


def test_macro_citation_is_a_clean_data_card():
    # PH-PROV3f: a non-document source (macro rates) → data-card evidence (exact values +
    # source + as_of), no PDF/evidence image.
    tool = {"name": "fred__interest_rates", "source": "BIS / FRED (central-bank policy rates)",
            "connector": "fred"}
    data = {"interest_rates": [
        {"bank": "FED", "name": "U.S. Federal Reserve", "rate": 4.375, "date": "2025-07-08"},
        {"bank": "FED", "name": "U.S. Federal Reserve", "rate": 4.5, "date": "2024-07-08"}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.table and c.table[0] == ["기관", "금리", "기준일"]
    assert c.table[1] == ["U.S. Federal Reserve", "4.375%", "2025-07-08"]   # newest first
    assert c.snippet and "4.375%" in c.snippet and c.as_of == "2025-07-08"
    assert c.evidence_image_url is None  # no document → no highlight, just the data card


def test_rag_filing_citation_carries_passage_evidence():
    # PH-PROV3e: a RAG hit from a filing (has an accession) → evidence link in text mode;
    # a news hit (no accession) gets none.
    tool = {"name": "rag__search", "connector": "rag", "source": "RAG"}
    filing = {"hits": [{"text": "TSMC fabricates Apple's custom silicon under a multi-year supply agreement.",
                        "provenance": {"source": "SEC EDGAR", "doc_type": "filing", "market": "US",
                                       "accession": "0000320193-24-000123", "ticker": "AAPL",
                                       "section": "p.12", "url": "https://sec.gov/i"}}]}
    c = A._citations(tool, {"data": filing})[0]
    assert c.evidence_image_url and "text=" in c.evidence_image_url
    assert "accession=0000320193-24-000123" in c.evidence_image_url and "market=US" in c.evidence_image_url

    news = {"hits": [{"text": "Apple shares rose.",
                      "provenance": {"source": "Reuters", "doc_type": "news", "market": "US", "url": "https://r"}}]}
    assert A._citations(tool, {"data": news})[0].evidence_image_url is None


def test_evidence_anchors_on_the_figure_the_answer_cites():
    # PH-PROV3d: evidence highlights the line the ANSWER cites (net income), not always revenue.
    from agentengine.evidence import evidence_url_for_answer

    data = {"income_statements": [
        {"revenue": 391035000000.0, "net_income": 93736000000.0, "report_period": "2024-09-28",
         "accession_number": "0000320193-24-000123"}]}
    u_ni = evidence_url_for_answer(data, "0000320193-24-000123", "320193", "US",
                                   "Apple's net income was $93,736 million in FY2024.")
    assert u_ni and "concept=NetIncomeLoss" in u_ni and "value=93736000000" in u_ni
    u_rev = evidence_url_for_answer(data, "0000320193-24-000123", "320193", "US",
                                    "Total net sales were $391,035 million.")
    assert u_rev and ("Revenue" in u_rev or "concept=Revenues" in u_rev) and "93736000000" not in u_rev
    # no answer → falls back to the representative headline (revenue)
    u_fb = evidence_url_for_answer(data, "0000320193-24-000123", "320193", "US", "")
    assert u_fb and "Revenue" in u_fb


def test_evidence_url_for_balance_sheet_instant_context():
    # PH-PROV2c: the balance_sheets tool (instant XBRL contexts) → evidence link for the
    # headline figure (total_assets → us-gaap:Assets), plus an extracted balance table.
    tool = {"name": "sec_edgar__balance_sheets", "source": "SEC EDGAR", "connector": "sec_edgar"}
    data = {"balance_sheets": [
        {"total_assets": 364980000000.0, "total_liabilities": 308030000000.0,
         "shareholders_equity": 56950000000.0, "report_period": "2025-09-27",
         "accession_number": "0000320193-25-000079"},
        {"total_assets": 364980000000.0, "report_period": "2024-09-28",
         "accession_number": "0000320193-24-000123"}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.evidence_image_url and "/evidence?" in c.evidence_image_url
    assert "concept=Assets" in c.evidence_image_url                      # total_assets → Assets
    assert "accession=0000320193-25-000079" in c.evidence_image_url      # newest period
    assert "report_period=2025-09-27" in c.evidence_image_url
    assert c.table and any("자산총계" in row for row in c.table)          # balance table rendered


def test_evidence_url_for_cash_flow_duration_context():
    # PH-PROV2c: the cash_flow_statements tool (duration contexts) → evidence link anchored
    # on operating cash flow (NetCashProvidedByUsedInOperatingActivities).
    tool = {"name": "sec_edgar__cash_flow_statements", "source": "SEC EDGAR", "connector": "sec_edgar"}
    data = {"cash_flow_statements": [
        {"net_cash_flow_from_operations": 118254000000.0, "net_cash_flow_from_investing": 9447000000.0,
         "net_cash_flow_from_financing": -108488000000.0, "report_period": "2025-09-27",
         "accession_number": "0000320193-25-000079"}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.evidence_image_url and "concept=NetCashProvidedByUsedInOperatingActivities" in c.evidence_image_url
    assert "report_period=2025-09-27" in c.evidence_image_url
    assert c.table and any("영업활동CF" in row for row in c.table)        # cash-flow table rendered


def test_evidence_url_none_for_non_filing_or_non_us():
    # prices (no filing) → no evidence URL
    c = A._citations({"name": "yahoo__prices", "source": "Yahoo Finance", "connector": "yahoo"},
                     {"data": {"ticker": "AAPL", "prices": [{"time": "2026-06-13", "close": 1.0}]}})[0]
    assert c.evidence_image_url is None


def test_rag_citation_builds_canonical_link_from_accession():
    # a RAG chunk with no url but a KR accession → DART viewer link (not linkless)
    tool = {"name": "rag__search", "connector": "rag", "source": "RAG"}
    result = {"data": {"hits": [{"text": "메모리 매출원가율 개선", "provenance": {
        "source": "OpenDART", "doc_type": "filing", "market": "KR",
        "accession": "20260605000073", "as_of": "2026-06-05"}}]}}
    cites = A._citations(tool, result)
    assert len(cites) == 1
    assert cites[0].url == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260605000073"
    assert cites[0].kind == "filing" and "메모리" in (cites[0].snippet or "")


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


# --- U3: connector-backed artifacts -------------------------------------------
def test_artifacts_from_prices_timeseries():
    tool = {"name": "yahoo__prices", "source": "Yahoo Finance"}
    # real Price shape: the date is in `time` (no `date` field), value in `close`
    result = {"data": {"ticker": "AAPL", "prices": [
        {"time": "2024-01-02", "close": 185.6}, {"time": "2024-01-03", "close": 184.2}]}}
    arts = A._artifacts(tool, result)
    assert len(arts) == 1
    a = arts[0]
    assert a.kind == "timeseries" and a.ticker == "AAPL" and a.source == "Yahoo Finance" and a.tool == "yahoo__prices"
    assert a.series[0].label == "종가" and len(a.series[0].points) == 2
    assert a.series[0].points[0].x == "2024-01-02" and a.series[0].points[0].y == 185.6
    assert a.as_of == "2024-01-03"


def test_artifacts_from_metrics_history_multi_series():
    tool = {"name": "datasets_store__metrics_history", "source": "ingestion store"}
    result = {"data": {"ticker": "AAPL", "metrics": [
        {"report_period": "2024-09-28", "gross_margin": 0.46, "net_margin": 0.24},
        {"report_period": "2025-09-27", "gross_margin": 0.47, "net_margin": 0.27}]}}
    a = A._artifacts(tool, result)[0]
    labels = {s.label for s in a.series}
    assert a.kind == "timeseries" and {"매출총이익률", "순이익률"} <= labels


def test_artifacts_none_for_unchartable_result():
    assert A._artifacts({"name": "sec_edgar__filings", "source": "SEC EDGAR"}, {"data": {"filings": []}}) == []


@respx.mock
async def test_run_agent_emits_price_artifact(monkeypatch):
    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"time": "2024-01-02", "close": 185.6}]},
                                    headers={"x-connector": "yahoo"}))
    res = await A.run_agent("AAPL price chart", "vgk_x")
    assert res.artifacts and res.artifacts[0].kind == "timeseries" and res.artifacts[0].source == "Yahoo Finance"


@respx.mock
async def test_chat_stream_emits_artifact_event(monkeypatch):
    from agentengine.chat import stream_chat

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"time": "2024-01-02", "close": 185.6}]},
                                    headers={"x-connector": "yahoo"}))
    events = [e async for e in stream_chat([{"role": "user", "content": "AAPL price chart"}], "vgk_x")]
    art = next((e for e in events if e["type"] == "artifact"), None)
    assert art and art["artifact"]["kind"] == "timeseries"
    assert events[-1]["type"] == "done" and events[-1]["artifacts"]


@respx.mock
async def test_refresh_artifact_refetches(monkeypatch):
    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"time": "2024-02-01", "close": 190.0}]},
                                    headers={"x-connector": "yahoo"}))
    a = await A.refresh_artifact("yahoo__prices",
                                 {"ticker": "AAPL", "interval": "day", "start_date": "2024-01-01", "end_date": "2024-02-01"},
                                 "vgk_x", title="AAPL 종가")
    assert a and a.kind == "timeseries" and a.as_of == "2024-02-01" and a.args["ticker"] == "AAPL"


@respx.mock
async def test_refresh_artifact_unknown_tool_returns_none(monkeypatch):
    _gw(monkeypatch)
    _catalog()
    assert await A.refresh_artifact("nope__x", {}, "vgk_x") is None


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


def test_number_sources_formats_indexed_block():
    # PH-4e: the numbered block the planner gets so its inline [n] matches the chips
    from agentengine.models import Citation
    block = A.number_sources([
        Citation(tool="t", source="Barron's", snippet="Nvidia and SpaceX", as_of="2026-06-12", index=1),
        Citation(tool="t", source="TipRanks", index=2),
        {"source": "X", "index": None},  # no index -> skipped
    ])
    lines = block.splitlines()
    assert lines[0] == "[1] Barron's · Nvidia and SpaceX · 2026-06-12"
    assert lines[1] == "[2] TipRanks"
    assert len(lines) == 2


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


# --- PH-15: LLM-assessed step budget + strict finalize ------------------------
async def test_assess_budget_uses_llm_then_clamps(monkeypatch):
    from agentengine.config import settings

    async def _eleven(task):
        return 11

    async def _huge(task):
        return 999

    # gemini backend → the light model's estimate is used (clamped to the cap)
    monkeypatch.setattr(A, "_llm_steps", _eleven)
    assert await A.assess_budget("엔비디아 공급망·리스크 공시 요약", backend="gemini") == 11
    monkeypatch.setattr(A, "_llm_steps", _huge)
    assert await A.assess_budget("x", backend="gemini") == settings.max_steps_cap  # clamped


async def test_assess_budget_falls_back_without_llm(monkeypatch):
    from agentengine.config import settings
    # stub backend never calls the model → plain default (no hardcoded keyword rules)
    assert await A.assess_budget("anything", backend="stub") == settings.max_steps

    async def _boom(task):
        raise RuntimeError("no key")

    monkeypatch.setattr(A, "_llm_steps", _boom)
    assert await A.assess_budget("anything", backend="gemini") == settings.max_steps  # graceful


def test_call_sig_detects_repeat():
    from agentengine.planner import Decision
    a = Decision(tool="sec_edgar__filings", args={"ticker": "NVDA"})
    b = Decision(tool="sec_edgar__filings", args={"ticker": "NVDA"})
    c = Decision(tool="sec_edgar__filings", args={"ticker": "AAPL"})
    assert A.call_sig(a) == A.call_sig(b) and A.call_sig(a) != A.call_sig(c)
    assert A.call_sig(Decision(final="done")) is None


def test_fallback_answer_is_nonempty_and_anchored():
    from agentengine.models import Citation
    out = A.fallback_answer([Citation(tool="t", source="SEC EDGAR", index=1),
                             Citation(tool="t", source="Reuters", index=2)])
    assert out and "Reached the step limit" not in out
    assert "SEC EDGAR" in out and A.has_anchors(out)
    assert A.fallback_answer([])  # still non-empty with no citations


@respx.mock
async def test_run_agent_recovers_from_stuck_planner(monkeypatch):
    # a planner that never finalizes (keeps proposing the same tool) must NOT leak
    # "Reached the step limit." — the repeat-guard + fallback yield a real answer.
    from agentengine.planner import Decision

    _gw(monkeypatch)
    _catalog()
    respx.route(method="GET", url__regex=r"http://gw\.test/prices").mock(
        return_value=httpx.Response(200, json={"ticker": "AAPL", "prices": [{"close": 1}]}, headers={"x-connector": "yahoo"})
    )

    class StuckPlanner:
        async def plan(self, task, tools, history, system=None, conversation=None,
                       force_final=False, sources=None):
            if force_final:
                return Decision(final="")  # empty even when forced → exercises the fallback
            return Decision(tool="yahoo__prices", args={"ticker": "AAPL"})

    monkeypatch.setattr(A, "get_planner", lambda _b=None: StuckPlanner())
    res = await A.run_agent("AAPL price please", "vgk_x")
    assert res.answer and "Reached the step limit" not in res.answer
    assert A.has_anchors(res.answer)              # fallback is source-anchored
    assert len(res.steps) <= 2                    # repeat-guard stopped the loop early


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
    assert events[-1] == {"type": "done", "citations": [], "artifacts": [], "refused": False}


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


def test_economic_indicator_citation_data_card():
    # PH-DATA-4: economic indicator (DBnomics) → data-card evidence (values + source).
    tool = {"name": "fred__economic_indicators", "source": "DBnomics", "connector": "fred"}
    data = {"slug": "cpi", "name": "US CPI", "unit": "index", "source": "DBnomics",
            "source_url": "https://db.nomics.world/BLS/cu/CUSR0000SA0",
            "observations": [{"date": "2025-11", "value": 318.0}, {"date": "2025-12", "value": 319.1}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.table and c.table[0] == ["기간", "US CPI"] and c.table[1][0] == "2025-12"  # newest first


# --- PH-DATA-5 / PH-9: KPI extraction from the filing-text corpus ---------
_KPI_TOOLS = {"rag__search": {"name": "rag__search", "connector": "rag", "path": "/rag/search",
                              "method": "POST", "params": [{"name": "query", "required": True}],
                              "markets": ["US", "KR"], "source": "Platform RAG"}}
_KPI_HITS = [{"text": "Total net sales were $391,035 million in fiscal 2024, up 2% year over year.",
              "score": 0.94, "provenance": {"source": "SEC EDGAR", "accession": "0000320193-24-000123",
              "ticker": "AAPL", "market": "US", "section": "p.30", "doc_type": "filing",
              "url": "https://www.sec.gov/x", "as_of": "2024-09-28"}}]


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits

    async def call_tool(self, tool, args):
        return {"status": 200, "connector": "rag", "data": {"hits": self._hits}}


async def test_kpi_extraction_assembles_sourced_kpis(monkeypatch):
    from agentengine import kpi as K

    async def fake_extract(model, ticker, passages):  # the LLM step, stubbed
        return [{"name": "Total net sales", "value": "391,035", "unit": "$M",
                 "period": "FY2024", "passage_index": 0}]
    monkeypatch.setattr(K, "_gemini_extract", fake_extract)
    out = await K.extract_kpis(_FakeClient(_KPI_HITS), _KPI_TOOLS, "AAPL", "US", backend="gemini", model="m")
    k = out["kpis"][0]
    assert k["name"] == "Total net sales" and k["value"] == "391,035"
    assert "accession=0000320193-24-000123" in (k["evidence_image_url"] or "")  # cited to the real filing line
    art = out["artifact"]
    assert art["kind"] == "kpi" and art["table"][0] == ["지표", "값", "기간"] and art["table"][1][0] == "Total net sales"
    assert out["citations"][0]["used"] is True and out["citations"][0]["evidence_image_url"]


async def test_kpi_extraction_drops_unsourced_or_bad_index(monkeypatch):
    from agentengine import kpi as K

    async def fake_extract(model, ticker, passages):
        return [{"name": "Made up", "value": "9", "passage_index": 7},      # index out of range → dropped
                {"name": "No value", "value": "", "passage_index": 0},      # no value → dropped
                {"name": "Net sales", "value": "391,035", "passage_index": 0}]
    monkeypatch.setattr(K, "_gemini_extract", fake_extract)
    out = await K.extract_kpis(_FakeClient(_KPI_HITS), _KPI_TOOLS, "AAPL", "US", backend="gemini", model="m")
    assert [k["name"] for k in out["kpis"]] == ["Net sales"]  # only the passage-tied, valued KPI survives


async def test_kpi_stub_backend_returns_passages_not_fabricated():
    from agentengine import kpi as K
    out = await K.extract_kpis(_FakeClient(_KPI_HITS), _KPI_TOOLS, "AAPL", "US", backend="stub", model="m")
    assert out["kpis"] == [] and out["artifact"] is None      # no key → never fabricate KPIs
    assert out["citations"][0]["evidence_image_url"] and "gemini" in out["note"]  # still show sourced passages


async def test_kpi_empty_corpus_is_honest():
    from agentengine import kpi as K
    out = await K.extract_kpis(_FakeClient([]), _KPI_TOOLS, "AAPL", "US", backend="gemini", model="m")
    assert out["kpis"] == [] and out["artifact"] is None and "indexed" in out["note"]


@respx.mock
def test_kpi_endpoint_routes_through_gateway(monkeypatch):
    _gw(monkeypatch)
    _catalog()
    respx.post("http://gw.test/rag/search").mock(return_value=httpx.Response(200, json={"hits": _KPI_HITS}))
    r = client.post("/agent/kpis", json={"ticker": "AAPL", "market": "US"})  # autouse fixture → stub backend
    assert r.status_code == 200
    b = r.json()
    assert b["ticker"] == "AAPL" and b["market"] == "US"
    assert b["citations"][0]["evidence_image_url"]  # sourced passage evidence even on the stub path


def test_technical_indicator_citation_data_card():
    # PH-DATA-6: technical indicators (computed from Yahoo) → descriptive data-card, not a signal.
    tool = {"name": "yahoo__technical_indicators", "connector": "yahoo",
            "source": "Technical indicators (computed from Yahoo Finance)"}
    data = {"ticker": "AAPL", "market": "US", "as_of": "2025-06-01", "note": "Descriptive…",
            "source": "Technical indicators (computed from Yahoo Finance)",
            "indicators": [
                {"key": "sma_20", "name": "SMA(20)", "pane": "price", "unit": "price",
                 "lines": [{"label": "SMA(20)", "latest": 195.5, "points": [{"date": "2025-06-01", "value": 195.5}]}]},
                {"key": "rsi_14", "name": "RSI(14)", "pane": "sub", "unit": "ratio_0_100",
                 "lines": [{"label": "RSI(14)", "latest": 62.3, "points": [{"date": "2025-06-01", "value": 62.3}]}]}]}
    c = A._citations(tool, {"data": data})[0]
    assert c.table and c.table[0] == ["지표", "최신값"]
    assert any(row[0] == "SMA(20)" for row in c.table) and any(row[0] == "RSI(14)" for row in c.table)
    assert "서술적" in (c.snippet or "")  # labeled descriptive, never a trading signal
