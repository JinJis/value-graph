"""The connector catalog — one ``ConnectorManifest`` per implemented data source.

This is the machine-readable description every later platform surface reads (REST
docs, MCP tool generation, RAG registration, entitlements, metering, governance).
Each resource's ``path`` must map to a real registered route (enforced by a test).
"""

from __future__ import annotations

from app.connectors.manifest import (
    ConnectorManifest,
    CostTier,
    Freshness,
    License,
    Provenance,
    Resource,
    ResourceParam,
    UpstreamCredential,
)

# --- reusable params -----------------------------------------------------
P_TICKER = ResourceParam(name="ticker", description="Ticker symbol (US: AAPL; KR: 005930).")
P_MARKET = ResourceParam(name="market", enum=["US", "KR"], description="Market (default US).")
P_PERIOD = ResourceParam(name="period", required=True, enum=["annual", "quarterly", "ttm"], description="Reporting period.")
P_LIMIT = ResourceParam(name="limit", type="integer", description="Max rows.")

# --- license policies ----------------------------------------------------
LIC_SEC = License(id="us-public-domain", redistribution=True, attribution_required=False,
                  note="U.S. government works (SEC EDGAR) are public domain.")
LIC_FRED = License(id="fred-terms", redistribution=True, attribution_required=True,
                   note="Most FRED series are freely usable; some carry source-specific restrictions — check per series.",
                   terms_url="https://fred.stlouisfed.org/legal/")
LIC_DART = License(id="kr-opendart", redistribution=True, attribution_required=True,
                   note="OpenDART (FSS) public disclosure data; attribute the source.",
                   terms_url="https://opendart.fss.or.kr/")
LIC_ECOS = License(id="kr-bok-ecos", redistribution=True, attribution_required=True,
                   note="Bank of Korea ECOS economic statistics; attribute the source.",
                   terms_url="https://ecos.bok.or.kr/")
LIC_YAHOO = License(id="restricted-byo", redistribution=False, attribution_required=True,
                    note="Yahoo Finance ToS restricts redistribution — internal/BYO-key use; not redistributable to tenants.")
LIC_NEWS = License(id="restricted-headlines", redistribution=False, attribution_required=True,
                   note="Publisher copyright — store links + minimal quoting only; not redistributable as full text.")
LIC_DERIVED = License(id="derived-public", redistribution=True, attribution_required=True,
                      note="Derived from public SEC/DART filings held in the ingestion store.")

# --- provenance specs ----------------------------------------------------
PROV_SEC = Provenance(source="SEC EDGAR", as_of_field="report_period", source_link_field="filing_url", freshness=Freshness.periodic)
PROV_SEC_FILINGS = Provenance(source="SEC EDGAR", as_of_field="filing_date", source_link_field="url", freshness=Freshness.periodic)
PROV_YAHOO = Provenance(source="Yahoo Finance", as_of_field="time", freshness=Freshness.eod)
PROV_FRED = Provenance(source="FRED (St. Louis Fed)", as_of_field="date", freshness=Freshness.periodic)
PROV_DART = Provenance(source="OpenDART (FSS)", as_of_field="report_period", source_link_field="filing_url", freshness=Freshness.periodic)
PROV_ECOS = Provenance(source="Bank of Korea ECOS", as_of_field="date", freshness=Freshness.periodic)
PROV_NEWS = Provenance(source="Google News", as_of_field="date", source_link_field="url", freshness=Freshness.realtime)
PROV_DART_FILINGS = Provenance(source="OpenDART (FSS)", as_of_field="filing_date", source_link_field="url", freshness=Freshness.periodic)


def _statements(market: str, prov: Provenance, cost: CostTier) -> list[Resource]:
    items = [
        ("income_statements", "/financials/income-statements", "IncomeStatementResponse", "Income statements."),
        ("balance_sheets", "/financials/balance-sheets", "BalanceSheetResponse", "Balance sheets."),
        ("cash_flow_statements", "/financials/cash-flow-statements", "CashFlowStatementResponse", "Cash flow statements."),
        ("all_financials", "/financials", "FinancialsResponse", "All three statements."),
    ]
    return [
        Resource(name=n, description=d, path=p, output_model=m, markets=[market], cost_tier=cost,
                 params=[P_TICKER, P_PERIOD, P_LIMIT, P_MARKET], provenance=prov)
        for n, p, m, d in items
    ]


CONNECTORS: list[ConnectorManifest] = [
    ConnectorManifest(
        id="sec_edgar", name="SEC EDGAR", domain="us-fundamentals",
        description="US company facts, XBRL financial statements, filings, earnings, insider (Form 4), 13F.",
        markets=["US"],
        upstream=UpstreamCredential(requires_key=False, key_env="SEC_EDGAR_USER_AGENT"),
        license=LIC_SEC,
        resources=[
            Resource(name="company_facts", description="Company facts.", path="/company/facts",
                     output_model="CompanyFactsResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[P_TICKER, ResourceParam(name="cik", description="SEC CIK."), P_MARKET], provenance=PROV_SEC),
            *_statements("US", PROV_SEC, CostTier.free),
            Resource(name="filings", description="SEC filings.", path="/filings", output_model="FilingsResponse",
                     markets=["US"], cost_tier=CostTier.free, params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_SEC_FILINGS),
            Resource(name="earnings", description="Earnings actuals (XBRL).", path="/earnings", output_model="EarningsResponse",
                     markets=["US"], cost_tier=CostTier.free, params=[P_TICKER, P_LIMIT], provenance=PROV_SEC),
            Resource(name="insider_trades", description="Insider trades (Form 4).", path="/insider-trades",
                     output_model="InsiderTradesResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_SEC_FILINGS),
            Resource(name="institutional_holdings", description="13F holdings (filer_cik mode).", path="/institutional-holdings",
                     output_model="InstitutionalHoldingsResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[ResourceParam(name="filer_cik", description="13F filer CIK."), P_LIMIT], provenance=PROV_SEC_FILINGS),
            Resource(name="metrics_snapshot", description="Derived valuation metrics snapshot.", path="/financial-metrics/snapshot",
                     output_model="FinancialMetricSnapshotResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[P_TICKER, P_MARKET], provenance=PROV_SEC),
        ],
    ),
    ConnectorManifest(
        id="yahoo", name="Yahoo Finance", domain="prices",
        description="End-of-day prices and snapshots for US and KR (.KS/.KQ). Delayed.",
        markets=["US", "KR"],
        upstream=UpstreamCredential(requires_key=False),
        license=LIC_YAHOO,
        resources=[
            Resource(name="prices", description="Historical EOD OHLCV.", path="/prices", output_model="PricesResponse",
                     cost_tier=CostTier.free, params=[
                         P_TICKER, ResourceParam(name="interval", required=True, enum=["day", "week", "month", "year"]),
                         ResourceParam(name="start_date", required=True, type="date"),
                         ResourceParam(name="end_date", required=True, type="date"), P_MARKET], provenance=PROV_YAHOO),
            Resource(name="price_snapshot", description="Latest price snapshot.", path="/prices/snapshot",
                     output_model="PriceSnapshotResponse", cost_tier=CostTier.free, params=[P_TICKER, P_MARKET], provenance=PROV_YAHOO),
        ],
    ),
    ConnectorManifest(
        id="fred", name="FRED (US macro)", domain="macro",
        description="US/global central-bank interest rates (FED/ECB/BOE/BOJ).",
        markets=["US"],
        upstream=UpstreamCredential(requires_key=True, key_env="FRED_API_KEY", signup_url="https://fred.stlouisfed.org/docs/api/api_key.html"),
        license=LIC_FRED,
        resources=[
            Resource(name="interest_rates", description="Historical interest rates.", path="/macro/interest-rates",
                     output_model="InterestRatesResponse", markets=["US"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="bank", required=True, enum=["FED", "ECB", "BOE", "BOJ"]), P_MARKET], provenance=PROV_FRED),
            Resource(name="interest_rates_snapshot", description="Latest interest rate.", path="/macro/interest-rates/snapshot",
                     output_model="InterestRatesResponse", markets=["US"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="bank", required=True, enum=["FED", "ECB", "BOE", "BOJ"]), P_MARKET], provenance=PROV_FRED),
        ],
    ),
    ConnectorManifest(
        id="opendart", name="OpenDART (KR)", domain="kr-fundamentals",
        description="KR company facts, financial statements, filings, earnings, insider (elestock), metrics.",
        markets=["KR"],
        upstream=UpstreamCredential(requires_key=True, key_env="OPENDART_API_KEY", signup_url="https://opendart.fss.or.kr/"),
        license=LIC_DART,
        resources=[
            Resource(name="company_facts", description="Company facts.", path="/company/facts", output_model="CompanyFactsResponse",
                     markets=["KR"], cost_tier=CostTier.low, params=[P_TICKER, P_MARKET], provenance=PROV_DART),
            *_statements("KR", PROV_DART, CostTier.low),
            Resource(name="filings", description="DART filings.", path="/filings", output_model="FilingsResponse",
                     markets=["KR"], cost_tier=CostTier.low, params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_DART_FILINGS),
            Resource(name="earnings", description="Earnings actuals (DART).", path="/earnings", output_model="EarningsResponse",
                     markets=["KR"], cost_tier=CostTier.low, params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_DART),
            Resource(name="insider_trades", description="Insider/major-shareholder reports.", path="/insider-trades",
                     output_model="InsiderTradesResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_DART_FILINGS),
            Resource(name="metrics_snapshot", description="Derived metrics snapshot.", path="/financial-metrics/snapshot",
                     output_model="FinancialMetricSnapshotResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[P_TICKER, P_MARKET], provenance=PROV_DART),
        ],
    ),
    ConnectorManifest(
        id="ecos", name="Bank of Korea ECOS", domain="macro",
        description="KR interest rates (BOK base rate).",
        markets=["KR"],
        upstream=UpstreamCredential(requires_key=True, key_env="ECOS_API_KEY", signup_url="https://ecos.bok.or.kr/api/"),
        license=LIC_ECOS,
        resources=[
            Resource(name="interest_rates", description="Historical BOK rates.", path="/macro/interest-rates",
                     output_model="InterestRatesResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="bank", required=True, enum=["BOK"]), P_MARKET], provenance=PROV_ECOS),
            Resource(name="interest_rates_snapshot", description="Latest BOK rate.", path="/macro/interest-rates/snapshot",
                     output_model="InterestRatesResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="bank", required=True, enum=["BOK"]), P_MARKET], provenance=PROV_ECOS),
        ],
    ),
    ConnectorManifest(
        id="google_news", name="Google News", domain="news",
        description="Company / market news headlines for US and KR (by company name).",
        markets=["US", "KR"],
        upstream=UpstreamCredential(requires_key=False),
        license=LIC_NEWS,
        resources=[
            Resource(name="news", description="Recent news articles.", path="/news", output_model="NewsResponse",
                     cost_tier=CostTier.free, params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_NEWS),
        ],
    ),
    ConnectorManifest(
        id="datasets_store", name="Ingestion Store (screener)", domain="screening",
        description="Cross-sectional screener + line-items over the point-in-time ingestion store.",
        markets=["US", "KR"],
        upstream=UpstreamCredential(requires_key=False),
        license=LIC_DERIVED,
        resources=[
            Resource(name="screener", description="Screen the ingested universe by financial criteria.",
                     method="POST", path="/financials/search/screener", output_model="FinancialsSearchResponse",
                     cost_tier=CostTier.free, params=[P_MARKET], provenance=Provenance(source="ingestion store (SEC/DART)", as_of_field="report_period", freshness=Freshness.periodic)),
            Resource(name="line_items", description="Fetch line items across tickers.", method="POST",
                     path="/financials/search/line-items", output_model="FinancialsSearchResponse", cost_tier=CostTier.free,
                     params=[], provenance=Provenance(source="ingestion store (SEC/DART)", as_of_field="report_period", freshness=Freshness.periodic)),
        ],
    ),
]


def get_catalog() -> list[ConnectorManifest]:
    return CONNECTORS


def get_connector(connector_id: str) -> ConnectorManifest | None:
    return next((c for c in CONNECTORS if c.id == connector_id), None)


def all_resource_paths() -> set[tuple[str, str]]:
    return {(r.method.upper(), r.path) for c in CONNECTORS for r in c.resources}
