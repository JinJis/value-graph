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
    from app.store.prices_ingest import run_prices_ingest
    await run_prices_ingest(market, tickers)


async def _run_corp_actions(market: str, tickers: list[str]) -> None:
    from app.store.prices_ingest import run_corp_actions_ingest
    await run_corp_actions_ingest(market, tickers)


async def _run_news(market: str, tickers: list[str]) -> None:
    from app.store.news_ingest import run_news_ingest
    await run_news_ingest(market=market, tickers=tickers)


async def _run_filing_text(market: str, tickers: list[str]) -> None:
    from app.store.filing_ingest import run_filing_text_ingest
    await run_filing_text_ingest(market, tickers)


async def _run_evidence_docs(market: str, tickers: list[str]) -> None:
    from app.store.evidence_docs import run_build_evidence_docs
    await run_build_evidence_docs(market, tickers)


# id → metadata + runner. `kind` is the IngestionJob kind the runner writes (so the admin
# can group jobs by pipeline). `default` = part of the standard scheduled set.
PIPELINES: list[dict] = [
    {"id": "financials", "label": "재무제표", "source": "SEC EDGAR · OpenDART", "store": "financial_facts",
     "kind": "backfill", "markets": ["US", "KR"], "default": True, "runner": _run_financials,
     "desc": "3대 재무제표 + 회사 정보(딥 백필)"},
    {"id": "prices", "label": "가격(OHLCV)", "source": "Yahoo Finance", "store": "price_bars",
     "kind": "prices", "markets": ["US", "KR"], "default": True, "runner": _run_prices,
     "desc": "일별 시·고·저·종가 + 거래량(2년)"},
    {"id": "corp_actions", "label": "배당·분할", "source": "Yahoo Finance", "store": "corporate_actions",
     "kind": "corp_actions", "markets": ["US", "KR"], "default": True, "runner": _run_corp_actions,
     "desc": "배당락일·금액 + 액면분할(10년)"},
    {"id": "news", "label": "뉴스 → RAG", "source": "Google News", "store": "RAG corpus",
     "kind": "news", "markets": ["US", "KR"], "default": True, "runner": _run_news,
     "desc": "종목별 최신 헤드라인을 RAG 색인"},
    {"id": "filing_text", "label": "공시 본문 → RAG", "source": "SEC/DART PDF", "store": "RAG corpus",
     "kind": "filing_text", "markets": ["US", "KR"], "default": False, "runner": _run_filing_text,
     "desc": "공시 PDF 본문을 RAG 색인(무거움)"},
    {"id": "evidence_docs", "label": "증거 PDF", "source": "SEC/DART", "store": "evidence_docs",
     "kind": "evidence_docs", "markets": ["US", "KR"], "default": False, "runner": _run_evidence_docs,
     "desc": "공시를 PDF로 캐시(증거 하이라이트, 무거움)"},
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
