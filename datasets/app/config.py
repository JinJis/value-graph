"""Application settings, loaded from environment / .env (pydantic-settings).

All upstream API keys live here and are read server-side only. Nothing in this
module is ever returned to a client.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read the shared platform env first, then any service-local .env override.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    # --- this service's own auth -------------------------------------------
    auth_disabled: bool = False
    # Comma-separated list of client keys accepted via the X-API-KEY header.
    datasets_api_keys: str = ""

    # --- US upstream credentials -------------------------------------------
    # SEC requires a descriptive User-Agent ("Sample Company name@example.com").
    sec_edgar_user_agent: str = "ValueGraph Datasets contact@example.com"
    fred_api_key: str = ""
    polygon_api_key: str = ""
    tiingo_api_key: str = ""
    fmp_api_key: str = ""

    # --- KR upstream credentials -------------------------------------------
    opendart_api_key: str = ""
    ecos_api_key: str = ""
    # CE-12: Korea Investment & Securities (KIS) — KR realtime rankings + investor flows.
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_domain: str = "https://openapi.koreainvestment.com:9443"  # 실전; 모의 = openapivts:29443
    krx_api_key: str = ""
    kis_app_key: str = ""
    kis_app_secret: str = ""

    # --- per-domain provider selection (override the free defaults) --------
    prices_provider_us: str = "yahoo"  # yahoo | stooq | polygon | tiingo | fmp
    prices_provider_kr: str = "yahoo"  # yahoo | pykrx | krx | kis
    # macro: FRED's api.stlouisfred.org serves a JS bot-wall to datacenter IPs, so
    # US macro breaks in the cloud. "auto" tries FRED when FRED_API_KEY is set and
    # falls back to keyless, cloud-safe DBnomics (BIS policy rates); "dbnomics"
    # forces the keyless path; "fred" forces FRED only.
    macro_provider_us: str = "auto"  # auto | fred | dbnomics

    # --- infra -------------------------------------------------------------
    # Ingestion store. SQLite by default (zero-setup, dev); set a postgresql://
    # URL in production. Used by the screener / line-items search.
    database_url: str = "sqlite:///./datasets.db"
    redis_url: str = ""
    cache_ttl_seconds: int = 900
    http_timeout_seconds: float = 30.0
    log_level: str = "INFO"  # app log verbosity (DEBUG|INFO|WARNING|…) → docker logs

    # --- periodic ingestion scheduler (PH-PIPE) ---------------------------
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 21600  # 6h between full sweeps by default
    # Universe to refresh — DYNAMIC source ids (see app/store/universes.py), fetched fresh each
    # sweep: "us_sp500,kr_kospi200,kr_kosdaq150" (also us_all / kr_kospi_all / kr_kosdaq_all), and/or
    # the legacy explicit form "US:AAPL,MSFT;KR:005930". Empty → scheduler idles.
    scheduler_universe: str = "us_sp500,kr_kospi200,kr_kosdaq150"
    # Which data pipelines each sweep runs (ids from app/pipelines.py). Empty → the
    # registry's default set (financials, prices, corp_actions, news).
    scheduler_pipelines: str = "financials,prices,corp_actions,news"
    # CE-0: how many years of daily OHLCV the prices pipeline stores. Deep enough for the
    # store-backed screener / quant / backtest (the chart fetches its own history live).
    prices_backfill_years: int = 5
    # how many recent filings filing_search fetches+indexes when a never-seen ticker is queried
    # on-demand (bounded so the first call stays responsive).
    filing_search_ingest_limit: int = 2

    # --- RAG news-ingestion pipeline (PH-2b) ------------------------------
    # The RAG service the news pipeline indexes into.
    rag_url: str = "http://rag:8002"
    # Headlines fetched per ticker per news-ingest run.
    news_ingest_limit: int = 8

    # --- PH-PROV2: deterministic visual evidence --------------------------
    # The renderer service that turns a fact locator into a highlighted screenshot.
    renderer_url: str = "http://renderer:8006"
    # PH-PROV3: cache each filing as a PDF during ingest so /evidence works for it
    # (US iXBRL→render · KR official PDF). Off by default (adds fetch/render time to ingest).
    precompute_locations: bool = False
    # Where cached PDF-normalized filings live (on the datasets data volume).
    evidence_docs_dir: str = "/data/evidence_docs"

    @property
    def accepted_api_keys(self) -> set[str]:
        return {k.strip() for k in self.datasets_api_keys.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
