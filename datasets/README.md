# ValueGraph Datasets API — US + Korea

A self-hosted financial-data API for the **US and Korean equity markets (KOSPI / KOSDAQ)**.
Request/response shapes are defined by `openapi.json` in this folder.

One API surface, two markets, selected with a `market` query parameter (default `US`, so requests
written against the original spec keep working):

```
GET /prices?ticker=AAPL&market=US&interval=day&start_date=2024-01-01&end_date=2024-02-01
GET /prices?ticker=005930&market=KR&interval=day&start_date=2024-01-01&end_date=2024-02-01
```

US tickers are alphabetic (`AAPL`); KR tickers are the 6-digit issue code (`005930`, `.KS`/`.KQ` accepted).

> **Platform note:** this service is the *data plane* of the new `platform/` workspace. Each data source
> is a **connector** that publishes a machine-readable manifest (resources, provenance, freshness, cost,
> required credential, **license/redistribution policy**). Browse it at `GET /catalog` and
> `GET /catalog/{id}` — this is the keystone the upcoming control-plane, MCP, RAG, and Agent Engine read.

---

## Contents
- [Status](#status) · [Quick start](#quick-start) · [Command cheat-sheet](#command-cheat-sheet)
- [API keys](#api-keys-all-free) · [Self-test from /docs](#self-test-from-docs)
- [Ingestion store & screener](#ingestion-store--screener) · [Scheduler](#scheduler-periodic-ingestion)
- [History depth](#history-depth) · [Config reference](#config-reference) · [Disclaimers](#disclaimers)

---

## Status

In `/docs`, anything under the **🚧 Not Implemented (501)** tag group (bottom) is not built yet and
returns HTTP 501. Everything else is real.

| Endpoint group | US source | KR source | Status |
|---|---|---|---|
| `/company/facts` (+ `/tickers`) | SEC EDGAR | OpenDART | ✅ |
| `/prices`, `/prices/snapshot` (+ `/tickers`) | Yahoo Finance (EOD) | Yahoo Finance `.KS`/`.KQ` | ✅ |
| `/financials/income-statements` · `/balance-sheets` · `/cash-flow-statements` · `/financials` | SEC XBRL | OpenDART | ✅ |
| `/filings` (+ `/types`) | SEC submissions | OpenDART | ✅ |
| `/macro/interest-rates` (+ `/snapshot`, `/banks`) | FRED | BOK ECOS | ✅ |
| `/financial-metrics/snapshot` | derived (XBRL + price) | derived (DART + price) | ✅ |
| `/news` | Google News RSS | Google News RSS | ✅ |
| `/earnings` | SEC XBRL actuals | OpenDART actuals | ✅ |
| `/insider-trades` | SEC Form 4 | OpenDART elestock | ✅ |
| `/institutional-holdings?filer_cik=` | SEC 13F info table | — | ✅ |
| `/financials/search/screener` · `/line-items` | ingestion store | ingestion store | ✅ |
| `/admin/selftest`, `/admin/scheduler`, `/admin/store/stats` | ops | ops | ✅ |
| `/financial-metrics` (historical), `/institutional-holdings?ticker=`, index-funds, KPIs, segments, as-reported, 13F discovery | — | — | 🚧 `501` |

> Prices default to keyless **Yahoo Finance** for both markets. Earnings consensus/surprise fields are
> intentionally null (no free estimates feed — never fabricated).

---

## Quick start

```bash
cd datasets
uv sync --extra dev
cp .env.example .env            # AUTH_DISABLED=true by default; add free keys you have
uv run uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs
```

Prices work with no keys (Yahoo). US company facts / financials / filings need only a
`SEC_EDGAR_USER_AGENT` string. KR fundamentals and macro need the free keys below.

---

## Command cheat-sheet

```bash
# --- run -------------------------------------------------------------------
uv run uvicorn app.main:app --reload              # dev server at :8000 (/docs)
uv run pytest -q                                  # unit tests
BASE=http://127.0.0.1:8000 bash scripts/smoke.sh  # curl smoke test (keyless + keyed)

# --- ingest the store (latest few periods) --------------------------------
uv run python -m scripts.ingest US AAPL MSFT NVDA
uv run python -m scripts.ingest KR 005930 000660 035720

# --- bulk / deep-history backfill -----------------------------------------
uv run python -m scripts.bulk_load US AAPL MSFT          # full companyfacts history per ticker (e.g. AAPL 2007→now)
uv run python -m scripts.bulk_load KR 005930 --limit 15  # DART deep, annual + quarterly
# full US universe (download the ~1GB zip once, then stream it):
curl -o /tmp/companyfacts.zip https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
uv run python -m scripts.bulk_load US --zip /tmp/companyfacts.zip --limit 500

# --- ops (also runnable from /docs under "Admin / Ops") -------------------
curl http://127.0.0.1:8000/admin/selftest          # live pass/fail of every endpoint
curl http://127.0.0.1:8000/admin/store/stats        # how much is ingested
curl http://127.0.0.1:8000/admin/scheduler          # scheduler status
curl -X POST http://127.0.0.1:8000/admin/scheduler/run     # ingest now
curl -X POST http://127.0.0.1:8000/admin/scheduler/pause
curl -X POST http://127.0.0.1:8000/admin/scheduler/resume

# --- docker ----------------------------------------------------------------
docker compose up --build                          # build + run, reads ./.env, :8000
docker compose down
docker build -t valuegraph-datasets:latest .
docker run -d --name valuegraph-datasets --env-file .env -p 8000:8000 valuegraph-datasets:latest
docker logs -f valuegraph-datasets ; docker rm -f valuegraph-datasets

# --- regenerate models from the spec --------------------------------------
uv run datamodel-codegen --input openapi.json --input-file-type openapi \
  --output app/models/generated.py --output-model-type pydantic_v2.BaseModel \
  --use-standard-collections --use-union-operator --snake-case-field
```

---

## API keys (all free)

| Env var | Unlocks | Get it at |
|---|---|---|
| `SEC_EDGAR_USER_AGENT` | 🇺🇸 company facts / financials / filings / earnings / insider / 13F (just a `name email` string) | — |
| `FRED_API_KEY` | 🇺🇸 macro / interest rates | https://fred.stlouisfed.org/docs/api/api_key.html |
| `OPENDART_API_KEY` | 🇰🇷 company facts / financials / filings / earnings / insider / metrics | https://opendart.fss.or.kr/ |
| `ECOS_API_KEY` | 🇰🇷 macro / base rate (Bank of Korea) | https://ecos.bok.or.kr/api/ |
| `DATASETS_API_KEYS` | client keys accepted via `X-API-KEY` (when `AUTH_DISABLED=false`) | set your own |

Set `AUTH_DISABLED=true` for local dev to skip `X-API-KEY` checks. Optional paid adapters:
`POLYGON_API_KEY`, `TIINGO_API_KEY`, `FMP_API_KEY`, `KIS_APP_KEY`/`KIS_APP_SECRET`.

> **FRED** sometimes serves a JS bot-challenge to datacenter IPs (returns 503 with a clear message);
> it responds normally from a residential IP / your own machine. The self-test marks this `skipped`.

---

## Self-test from /docs

`GET /admin/selftest` drives a curated set of implemented endpoints (US + KR) through the real stack
and returns a per-check report — run it from **/docs → Admin / Ops → /admin/selftest → Try it out**.

```jsonc
{
  "summary": { "total": 19, "passed": 18, "failed": 0, "skipped": 1 },
  "checks": [
    { "name": "US prices (AAPL)", "endpoint": "GET /prices", "result": "pass", "http_status": 200, "latency_ms": 410 },
    { "name": "US macro / fed funds (FRED)", "result": "skipped", "http_status": 503, "detail": "upstream key or IP not available" }
    // ...
  ]
}
```
`pass` = 200 · `skipped` = an upstream key/IP isn't available here (not a code failure) · `fail` = needs attention.

---

## Ingestion store & screener

Cross-sectional endpoints (`/financials/search/screener`, `/financials/search/line-items`) query a
local **ingestion store** instead of fetching per-ticker upstream — that's what makes universe-wide
filtering and deep history possible. The store is **point-in-time** (restatements kept, not
overwritten). SQLite by default; set `DATABASE_URL=postgresql://…` for production.

**Deep history** comes from the bulk loader: per ticker it loads *every* annual + quarterly period
from companyfacts (AAPL → back to 2007), and `--zip` streams the full SEC dump for the whole universe.
Set `SCHEDULER_DEEP=true` to make periodic runs do deep backfill. See the cheat-sheet for `scripts.bulk_load`.

```bash
uv run python -m scripts.ingest US AAPL MSFT NVDA        # latest few periods
uv run python -m scripts.bulk_load US AAPL MSFT NVDA     # deep/full history

curl -X POST "http://127.0.0.1:8000/financials/search/screener?market=US" -H "Content-Type: application/json" \
  -d '{"limit":10,"filters":[{"field":"revenue","operator":"gt","value":100000000000},
                              {"field":"net_income","operator":"gt","value":50000000000}]}'

curl -X POST "http://127.0.0.1:8000/financials/search/line-items" -H "Content-Type: application/json" \
  -d '{"line_items":["revenue","net_income"],"tickers":["AAPL","005930"],"period":"annual","limit":3}'
```

---

## Scheduler (periodic ingestion)

A background task refreshes the store on an interval. Disabled by default — enable and point it at a
universe via env, then monitor/control it from `/admin/scheduler` (also in /docs):

```bash
# .env
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=3600
SCHEDULER_UNIVERSE=US:AAPL,MSFT,NVDA;KR:005930,000660
```

| Endpoint | Purpose |
|---|---|
| `GET /admin/scheduler` | status: enabled, running, run_count, last_run_at, last_status, last_summary |
| `POST /admin/scheduler/run` | trigger an ingestion run now |
| `POST /admin/scheduler/pause` / `resume` | stop / start the periodic loop |
| `GET /admin/store/stats` | ingested facts/companies + report-period coverage per market |

---

## History depth

Deep history comes from bulk backfill into the point-in-time store, then incremental refresh. Free
sources bottom out at different points — gaps are surfaced honestly, never fabricated:

| Domain | Free history floor |
|---|---|
| US prices | ~1980s (Yahoo) |
| US filings (list/text) | 1994+ (EDGAR full-index) |
| US structured fundamentals (XBRL) | ~2009+ (XBRL mandate) |
| US 13F | ~2013+ |
| KR fundamentals (DART API) | ~2015+ |
| KR prices | ~2000+ |

Going earlier needs legacy-filing parsing or a licensed dataset.

---

## Config reference

| Env var | Default | Notes |
|---|---|---|
| `AUTH_DISABLED` | `false` | `true` skips `X-API-KEY` checks (dev) |
| `DATABASE_URL` | `sqlite:///./datasets.db` | `postgresql://…` in prod |
| `PRICES_PROVIDER_US` / `_KR` | `yahoo` | `yahoo`\|`stooq`\|`pykrx` |
| `CACHE_TTL_SECONDS` | `900` | upstream response cache TTL |
| `SCHEDULER_ENABLED` | `false` | enable periodic ingestion |
| `SCHEDULER_INTERVAL_SECONDS` | `3600` | refresh interval |
| `SCHEDULER_UNIVERSE` | — | `US:AAPL,MSFT;KR:005930` |

Full list in `.env.example`.

---

## Disclaimers

- **Not investment advice.** Data is provided as-is for research/engineering.
- **Licensing:** price/market-cap data is **delayed / end-of-day** by default. Respect each source's
  terms before redistribution. Filing full text is not redistributed — only extracted numbers + links.
- LLM/API keys are server-side only.
