# ValueGraph Datasets API — US + Korea

A self-hosted financial-data API modeled on the [financialdatasets.ai](https://financialdatasets.ai) spec
(`openapi.json` in this folder) and **extended to cover the Korean equity market (KOSPI / KOSDAQ)**.

One API surface, two markets, selected with a `market` query parameter:

```
GET /prices?ticker=AAPL&market=US&interval=day&start_date=2024-01-01&end_date=2024-02-01
GET /prices?ticker=005930&market=KR&interval=day&start_date=2024-01-01&end_date=2024-02-01
```

`market` defaults to `US`, so requests written against the original financialdatasets.ai spec keep working.

## Status

This is a **vertical slice**: a core set of endpoint groups returns real data for **both US and KR**;
the rest of the spec surface is scaffolded (visible in `/docs`, returns `501 Not Implemented`).

| Endpoint group | US source | KR source | Status |
|---|---|---|---|
| `/company/facts` (+ `/tickers`) | SEC EDGAR | OpenDART | ✅ |
| `/prices`, `/prices/snapshot` (+ `/tickers`) | Yahoo Finance (EOD) | Yahoo Finance `.KS`/`.KQ` (EOD) | ✅ |
| `/financials/income-statements` · `/balance-sheets` · `/cash-flow-statements` · `/financials` | SEC XBRL | OpenDART | ✅ |
| `/filings` (+ `/types`) | SEC submissions | OpenDART | ✅ |
| `/macro/interest-rates`, `/snapshot`, `/banks` | FRED | BOK ECOS | ✅ |
| `/financial-metrics/snapshot` | derived (SEC XBRL + price) | derived (OpenDART + price) | ✅ |
| `/financial-metrics` (historical) | — | — | 🚧 `501` |
| insider-trades, institutional-holdings, index-funds, earnings, news, KPIs, segments, as-reported, screener | — | — | 🚧 scaffolded (`501`) |

Prices default to the keyless **Yahoo Finance** chart API for both markets (delayed/EOD).
`pykrx` (KRX/Naver) is available as `PRICES_PROVIDER_KR=pykrx`, and `stooq` as `PRICES_PROVIDER_US=stooq`,
but both reach KRX/stooq directly and may be blocked from some server environments.

Financial statements support `period=annual|quarterly|ttm` (US TTM = last FY + latest YTD − prior-year
YTD for flows, latest instant for the balance sheet) and the `report_period[_gte|_lte|_gt|_lt]` filters.
Price `interval` accepts `day|week|month|year` (`year` is served as monthly bars by Yahoo).

## Quick start

```bash
cd datasets
uv sync --extra dev
cp .env.example .env                # AUTH_DISABLED=true by default; fill in free keys you have
uv run uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs

# (optional) regenerate the Pydantic models from the spec:
uv run datamodel-codegen --input openapi.json --input-file-type openapi \
  --output app/models/generated.py --output-model-type pydantic_v2.BaseModel \
  --use-standard-collections --use-union-operator --snake-case-field
```

**Prices for both US and KR work with no API keys** (Yahoo Finance). US company facts / financials /
filings need only a `SEC_EDGAR_USER_AGENT` contact string (no signup). The KR equivalents and all
macro need the free keys below.

## Docker

The image bundles all dependencies (uv, FastAPI, pandas/pykrx). Keys are passed at **runtime** via
`--env-file` / compose `env_file` — never baked into the image.

```bash
cd datasets
cp .env.example .env          # fill in your free keys

# --- docker compose (recommended) ---
docker compose up --build     # builds + runs, reads ./.env, serves on :8000
docker compose down

# --- or plain docker ---
docker build -t valuegraph-datasets:latest .
docker run -d --name valuegraph-datasets --env-file .env -p 8000:8000 valuegraph-datasets:latest

# verify
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/prices?ticker=AAPL&market=US&interval=day&start_date=2024-01-02&end_date=2024-01-05"
curl "http://127.0.0.1:8000/financials/income-statements?ticker=005930&market=KR&period=annual&limit=1"

# logs / stop
docker logs -f valuegraph-datasets
docker rm -f valuegraph-datasets
```

> Override a single key without editing `.env`: add `-e FRED_API_KEY=...` to `docker run`, or an
> `environment:` entry in `docker-compose.yml`. FRED is IP-gated from some datacenters (see Disclaimers).

## API keys (all free)

| Env var | Used for | Get it at |
|---|---|---|
| `SEC_EDGAR_USER_AGENT` | US filings/financials/company facts (SEC requires a UA: `name email`) | — (just set a contact string) |
| `FRED_API_KEY` | US macro / interest rates | https://fred.stlouisfed.org/docs/api/api_key.html |
| `OPENDART_API_KEY` | KR company facts / financials / filings | https://opendart.fss.or.kr/ |
| `ECOS_API_KEY` | KR macro / interest rates (Bank of Korea) | https://ecos.bok.or.kr/api/ |
| `KRX_API_KEY` | (optional) official KRX OPEN API instead of pykrx scraping | https://openapi.krx.co.kr/ |
| `DATASETS_API_KEYS` | comma-separated client keys this service accepts via `X-API-KEY` | — (set your own) |

Paid adapters (`POLYGON_API_KEY`, `TIINGO_API_KEY`, `FMP_API_KEY`, `KIS_APP_KEY`/`KIS_APP_SECRET`) are
optional and selected per-domain via `*_PROVIDER_US` / `*_PROVIDER_KR` overrides.

Set `AUTH_DISABLED=true` for local development to skip `X-API-KEY` checks.

## Disclaimers

- **Not investment advice.** Data is provided as-is for research/engineering.
- **Licensing:** price/market-cap data is provided **delayed / end-of-day** by default. pykrx scrapes
  KRX/Naver; respect each source's terms before redistribution. Do not redistribute filing full text —
  this service stores extracted numbers + source links.
- LLM/API keys are server-side only.
