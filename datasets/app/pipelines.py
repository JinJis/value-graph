"""Data-collection pipeline registry (PH-PIPE).

ONE declarative list of every periodic data pipeline the platform runs — what it
collects, from which source, into which store, and the runner that does it. The
scheduler and the admin backfill UI both derive from this (single source of truth,
like the connector manifest). Each runner self-records an ``IngestionJob`` (its
``kind``) and is best-effort per ticker, so the orchestrator just dispatches.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# --- runners (thin adapters over the existing/new ingest functions) -------
async def _run_financials(market: str, tickers: list[str]) -> None:
    from app.store.jobs import run_backfill
    await run_backfill(market=market, tickers=tickers, deep=True)


async def _run_prices(market: str, tickers: list[str]) -> None:
    from app.config import settings
    from app.store.prices_ingest import run_prices_ingest
    await run_prices_ingest(market, tickers, years=settings.prices_backfill_years)


async def _run_corp_actions(market: str, tickers: list[str]) -> None:
    from app.store.prices_ingest import run_corp_actions_ingest
    await run_corp_actions_ingest(market, tickers)


async def _run_news(market: str, tickers: list[str]) -> None:
    from app.store.news_ingest import run_news_ingest
    await run_news_ingest(market=market, tickers=tickers)


async def _run_filing_text(market: str, tickers: list[str]) -> None:
    from app.store.filing_ingest import run_filing_text_ingest
    await run_filing_text_ingest(market, tickers)


# pipeline cadence tiers — the scheduler skips a pipeline that ran within `min_interval_seconds`,
# so heavy historical pulls don't re-fetch the full history every sweep. Pairs with incremental
# fetch in the runners (prices/corp_actions only pull since the last stored date).
_HOUR, _DAY, _WEEK = 3600, 86400, 604800

# id → metadata + runner. `kind` is the IngestionJob kind the runner writes (so the admin
# can group jobs by pipeline). `default` = part of the standard scheduled set.
# `upstream` = the EXACT external API(s) + request each pipeline issues (so the admin can show
# operators "어떤 API를 어떤 쿼리로 fetch하는지" verbatim). `fetch` = scope + re-fetch behavior.
# `min_interval_seconds` = cadence tier (how often the scheduler re-runs this pipeline).
PIPELINES: list[dict] = [
    {"id": "financials", "label": "재무제표", "source": "SEC EDGAR · OpenDART", "store": "financial_facts",
     "kind": "backfill", "markets": ["US", "KR"], "default": True, "runner": _run_financials,
     "min_interval_seconds": _WEEK,
     "desc": "3대 재무제표 + 회사 정보(딥 백필)",
     "upstream": [
         "US · SEC EDGAR (XBRL) — GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
         "US · SEC EDGAR (필링 목록) — GET https://data.sec.gov/submissions/CIK{cik}.json",
         "KR · OpenDART — GET https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
         "?corp_code={corp}&bsns_year={YYYY}&reprt_code={11011|11012|11013|11014}&fs_div=CFS",
     ],
     "fetch": "US: 전 기간 연·분기 XBRL 재무사실 / KR: 최근 15개 보고서(연·분기). UPSERT 키 "
              "(market,ticker,statement,line_item,period,report_period,accession). ⚠️ 매 실행 전체 재수집(증분 없음)."},
    {"id": "prices", "label": "가격(OHLCV)", "source": "Yahoo Finance", "store": "price_bars",
     "kind": "prices", "markets": ["US", "KR"], "default": True, "runner": _run_prices,
     "min_interval_seconds": _DAY,
     "desc": "일별 시·고·저·종가 + 거래량",
     "upstream": [
         "US·KR · Yahoo Finance chart — GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
         "?period1={start_epoch}&period2={end_epoch}&interval=1d",
     ],
     "fetch": "일봉 OHLCV+거래량. UPSERT 키 (market,ticker,interval,bar_date). "
              "✅ 증분: 종목별 마지막 저장일 이후만 fetch(최초 1회만 PRICES_BACKFILL_YEARS년 전체)."},
    {"id": "corp_actions", "label": "배당·분할", "source": "Yahoo Finance", "store": "corporate_actions",
     "kind": "corp_actions", "markets": ["US", "KR"], "default": True, "runner": _run_corp_actions,
     "min_interval_seconds": _WEEK,
     "desc": "배당락일·금액 + 액면분할(10년)",
     "upstream": [
         "US·KR · Yahoo Finance chart events — GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
         "?period1={start_epoch}&period2={end_epoch}&interval=1d&events=div,split",
     ],
     "fetch": "배당락일·금액 + 액면분할 비율. UPSERT 키 (market,ticker,kind,event_date). "
              "✅ 증분: 종목별 마지막 이벤트일 이후만 fetch(최초 1회만 10년 전체)."},
    {"id": "news", "label": "뉴스 → RAG", "source": "Google News", "store": "RAG corpus",
     "kind": "news", "markets": ["US", "KR"], "default": True, "runner": _run_news,
     "min_interval_seconds": _HOUR,
     "desc": "종목별 최신 헤드라인을 RAG 색인",
     "upstream": [
         "US·KR · Google News RSS — GET https://news.google.com/rss/search"
         "?q={회사명 또는 티커}&hl={ko|en-US}&gl={KR|US}&ceid={KR:ko|US:en}",
     ],
     "fetch": "종목별 최신 헤드라인 NEWS_INGEST_LIMIT건(기본 8) → RAG 색인(doc_id=url). "
              "과거 이력 없음 — 최신 N건만 반환(본질적으로 증분)."},
    {"id": "filing_text", "label": "공시 본문 → RAG", "source": "SEC/DART PDF", "store": "RAG corpus",
     "kind": "filing_text", "markets": ["US", "KR"], "default": False, "runner": _run_filing_text,
     "min_interval_seconds": _WEEK,
     "desc": "공시 PDF 본문을 RAG 색인(무거움)",
     "upstream": [
         "US · SEC iXBRL 본문 — GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}",
         "KR · OpenDART document.xml — GET https://opendart.fss.or.kr/api/document.xml?rcept_no={rcept_no}",
     ],
     "fetch": "재무제표에 등장한 최근 4개 공시 본문 HTML을 텍스트 추출→RAG 색인(doc_id={accession}:s.{n}). "
              "HTML은 인앱 뷰어와 동일 원천을 공유·캐시(증분)."},
]

PIPELINE_BY_ID = {p["id"]: p for p in PIPELINES}
KIND_TO_PIPELINE = {p["kind"]: p for p in PIPELINES}


def list_pipelines() -> list[dict]:
    """Pipeline metadata (no runner) for the admin/scheduler views."""
    return [{k: v for k, v in p.items() if k != "runner"} for p in PIPELINES]


def default_pipeline_ids() -> list[str]:
    return [p["id"] for p in PIPELINES if p["default"]]


def resolve_pipeline_ids(ids: list[str] | None) -> list[str]:
    """Validate requested ids against the registry; fall back to the default set."""
    if not ids:
        return default_pipeline_ids()
    valid = [i for i in ids if i in PIPELINE_BY_ID]
    return valid or default_pipeline_ids()


async def run_pipelines(market: str, tickers: list[str], pipeline_ids: list[str] | None = None) -> dict:
    """Run the selected pipelines over one (market, tickers) set. Each runner self-records its
    IngestionJob and is best-effort; we only catch a hard runner crash so one pipeline never
    sinks the rest. Returns {pipeline_id: 'ok' | 'skipped' | 'error: …'}."""
    ids = resolve_pipeline_ids(pipeline_ids)
    summary: dict[str, str] = {}
    for p in PIPELINES:
        if p["id"] not in ids:
            continue
        if market not in p["markets"]:
            summary[p["id"]] = "skipped"
            continue
        try:
            await p["runner"](market, tickers)
            summary[p["id"]] = "ok"
        except Exception as exc:  # noqa: BLE001 — one pipeline failing never sinks the others
            logger.warning("pipeline %s failed for %s: %s", p["id"], market, exc)
            summary[p["id"]] = f"error: {exc}"
    return summary
