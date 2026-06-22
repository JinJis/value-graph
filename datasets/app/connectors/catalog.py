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

# Shared vocabulary (reusable params, license policies, provenance specs) lives in
# a sibling so the governance constants stay apart from the connector listing below.
from app.connectors.catalog_policies import (
    LIC_DART,
    LIC_DERIVED,
    LIC_ECOS,
    LIC_FRED,
    LIC_NEWS,
    LIC_SEC,
    LIC_YAHOO,
    P_LIMIT,
    P_MARKET,
    P_PERIOD,
    P_TICKER,
    P_TICKER_REQ,
    PROV_DART,
    PROV_DART_FILINGS,
    PROV_ECOS,
    PROV_DBNOMICS,
    PROV_FRED,
    PROV_NEWS,
    PROV_SEC,
    PROV_SEC_FILINGS,
    PROV_TECHNICAL,
    PROV_YAHOO,
)


def _statements(market: str, prov: Provenance, cost: CostTier) -> list[Resource]:
    items = [
        ("income_statements", "/financials/income-statements", "IncomeStatementResponse", "Income statements."),
        ("balance_sheets", "/financials/balance-sheets", "BalanceSheetResponse", "Balance sheets."),
        ("cash_flow_statements", "/financials/cash-flow-statements", "CashFlowStatementResponse", "Cash flow statements."),
        ("all_financials", "/financials", "FinancialsResponse", "All three statements."),
    ]
    return [
        Resource(name=n, description=d, path=p, output_model=m, markets=[market], cost_tier=cost,
                 params=[P_TICKER_REQ, P_PERIOD, P_LIMIT, P_MARKET], provenance=prov)
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
            Resource(name="company_search", description="Search companies by name or ticker.",
                     path="/company/search", output_model="CompanySearchResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[ResourceParam(name="q", required=True, description="Name or ticker query."),
                             P_LIMIT, P_MARKET], provenance=PROV_SEC),
            *_statements("US", PROV_SEC, CostTier.free),
            Resource(name="filings", description="SEC filings.", path="/filings", output_model="FilingsResponse",
                     markets=["US"], cost_tier=CostTier.free, params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_SEC_FILINGS),
            Resource(name="earnings", description="Earnings actuals (XBRL).", path="/earnings", output_model="EarningsResponse",
                     markets=["US"], cost_tier=CostTier.free, params=[P_TICKER_REQ, P_LIMIT], provenance=PROV_SEC),
            Resource(name="insider_trades", description="Insider trades (Form 4).", path="/insider-trades",
                     output_model="InsiderTradesResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_SEC_FILINGS),
            Resource(name="institutional_holdings", description="13F holdings (filer_cik mode).", path="/institutional-holdings",
                     output_model="InstitutionalHoldingsResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[ResourceParam(name="filer_cik", description="13F filer CIK."), P_LIMIT], provenance=PROV_SEC_FILINGS),
            Resource(name="index_funds", description="ETF/index-fund holdings (constituents) from SEC N-PORT.",
                     path="/index-funds", output_model="IndexFundHoldingsResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[ResourceParam(name="ticker", description="Fund/ETF ticker (e.g. SPY)."), P_LIMIT, P_MARKET],
                     provenance=PROV_SEC_FILINGS),
            Resource(name="gurus", description="Superinvestor (Buffett/Burry/Ackman…) 13F portfolios; holdings cited to SEC.",
                     path="/gurus", output_model="InstitutionalHoldingsResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[ResourceParam(name="slug", description="Guru slug (e.g. buffett); omit to list all."), P_LIMIT],
                     provenance=PROV_SEC_FILINGS),
            Resource(name="metrics_snapshot", description="Derived valuation metrics snapshot.", path="/financial-metrics/snapshot",
                     output_model="FinancialMetricSnapshotResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[P_TICKER_REQ, P_MARKET], provenance=PROV_SEC),
            Resource(name="comparables", description="Peer valuation comparables — multiples side by side for a set of tickers.",
                     path="/comparables", output_model="FinancialMetricSnapshotResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[ResourceParam(name="tickers", required=True, description="Comma-separated peers, e.g. AAPL,MSFT,GOOGL"),
                             P_MARKET], provenance=PROV_SEC),
            Resource(name="as_reported", description="Financials exactly as reported in XBRL (raw us-gaap concepts, per period).",
                     path="/financials/as-reported", output_model="AsReportedResponse", markets=["US"], cost_tier=CostTier.free,
                     params=[P_TICKER_REQ, ResourceParam(name="period", enum=["annual", "quarterly", "ttm"]), P_LIMIT, P_MARKET],
                     provenance=PROV_SEC),
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
                         P_TICKER_REQ, ResourceParam(name="interval", required=True, enum=["day", "week", "month", "year"]),
                         ResourceParam(name="start_date", required=True, type="date"),
                         ResourceParam(name="end_date", required=True, type="date"), P_MARKET], provenance=PROV_YAHOO),
            Resource(name="price_snapshot", description="Latest price snapshot.", path="/prices/snapshot",
                     output_model="PriceSnapshotResponse", cost_tier=CostTier.free, params=[P_TICKER_REQ, P_MARKET], provenance=PROV_YAHOO),
            Resource(name="corporate_actions", description="Dividends + stock splits history.", path="/corporate-actions",
                     output_model="CorporateActionsResponse", cost_tier=CostTier.free,
                     params=[P_TICKER_REQ, ResourceParam(name="years", type="integer", description="Look-back years."), P_MARKET],
                     provenance=PROV_YAHOO),
            Resource(name="technical_indicators",
                     description="Descriptive technical indicators (SMA/EMA/RSI/MACD/Bollinger/volatility) computed from prices — not signals.",
                     path="/technical-indicators", output_model="TechnicalIndicatorsResponse", cost_tier=CostTier.free,
                     params=[P_TICKER_REQ,
                             ResourceParam(name="indicators", description="Comma list e.g. sma_50,ema_20,rsi_14,macd,bbands_20."),
                             ResourceParam(name="interval", enum=["day", "week", "month", "year"]),
                             ResourceParam(name="start_date", type="date"), ResourceParam(name="end_date", type="date"), P_MARKET],
                     provenance=PROV_TECHNICAL),
            Resource(name="asset_classes",
                     description="Cross-asset snapshot (자산군): indices, rates, commodities, FX, crypto — descriptive levels + day change.",
                     path="/market/asset-classes", output_model="CrossAssetResponse", cost_tier=CostTier.free,
                     params=[], provenance=PROV_YAHOO),
        ],
    ),
    ConnectorManifest(
        id="fred", name="FRED / DBnomics (US macro)", domain="macro",
        description="US/global central-bank policy rates (FED/ECB/BOE/BOJ). Keyless and cloud-safe by "
                    "default via DBnomics (BIS); falls back to FRED only when FRED_API_KEY is set.",
        markets=["US"],
        upstream=UpstreamCredential(requires_key=False),
        license=LIC_FRED,
        resources=[
            Resource(name="interest_rates", description="Historical interest rates.", path="/macro/interest-rates",
                     output_model="InterestRatesResponse", markets=["US"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="bank", required=True, enum=["FED", "ECB", "BOE", "BOJ"]), P_MARKET], provenance=PROV_FRED),
            Resource(name="interest_rates_snapshot", description="Latest interest rate.", path="/macro/interest-rates/snapshot",
                     output_model="InterestRatesResponse", markets=["US"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="bank", required=True, enum=["FED", "ECB", "BOE", "BOJ"]), P_MARKET], provenance=PROV_FRED),
            Resource(name="economic_indicators", description="Economic indicators (CPI, unemployment, GDP, …) via DBnomics.",
                     path="/macro/indicators", output_model="EconomicIndicatorsResponse", markets=["US"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="indicator", description="Indicator slug (e.g. cpi); omit to list all."),
                             ResourceParam(name="limit", type="integer", description="Recent observations.")],
                     provenance=PROV_DBNOMICS),
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
            Resource(name="company_search", description="Search companies by name or ticker.",
                     path="/company/search", output_model="CompanySearchResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="q", required=True, description="Name or ticker query."),
                             P_LIMIT, P_MARKET], provenance=PROV_DART),
            *_statements("KR", PROV_DART, CostTier.low),
            Resource(name="filings", description="DART filings.", path="/filings", output_model="FilingsResponse",
                     markets=["KR"], cost_tier=CostTier.low, params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_DART_FILINGS),
            Resource(name="earnings", description="Earnings actuals (DART).", path="/earnings", output_model="EarningsResponse",
                     markets=["KR"], cost_tier=CostTier.low, params=[P_TICKER_REQ, P_LIMIT, P_MARKET], provenance=PROV_DART),
            Resource(name="insider_trades", description="Insider/major-shareholder reports.", path="/insider-trades",
                     output_model="InsiderTradesResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[P_TICKER, P_LIMIT, P_MARKET], provenance=PROV_DART_FILINGS),
            Resource(name="metrics_snapshot", description="Derived metrics snapshot.", path="/financial-metrics/snapshot",
                     output_model="FinancialMetricSnapshotResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[P_TICKER_REQ, P_MARKET], provenance=PROV_DART),
            Resource(name="comparables", description="Peer valuation comparables — multiples side by side for a set of tickers.",
                     path="/comparables", output_model="FinancialMetricSnapshotResponse", markets=["KR"], cost_tier=CostTier.low,
                     params=[ResourceParam(name="tickers", required=True, description="Comma-separated peers, e.g. 005930,000660"),
                             P_MARKET], provenance=PROV_DART),
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
            Resource(name="metrics_history", description="Derived financial ratios across periods (margins, returns, leverage, growth).",
                     path="/financial-metrics", output_model="FinancialMetricsHistoryResponse", markets=["US", "KR"], cost_tier=CostTier.free,
                     params=[P_TICKER_REQ, ResourceParam(name="period", enum=["annual", "quarterly", "ttm"]), P_LIMIT, P_MARKET],
                     provenance=Provenance(source="ingestion store (SEC/DART)", as_of_field="report_period", freshness=Freshness.periodic)),
        ],
    ),
    ConnectorManifest(
        id="rag", name="Document RAG (filings/news)", domain="retrieval",
        description="Semantic search over ingested filings/news/transcripts; returns passages with provenance.",
        markets=["US", "KR"],
        service="rag",  # served by the RAG service, not the data plane
        upstream=UpstreamCredential(requires_key=False),
        license=License(
            id="rag-derived", redistribution=False, attribution_required=True,
            note="Passages may include copyrighted source text — cite + link, minimal quoting.",
        ),
        resources=[
            Resource(
                name="search", description="Retrieve relevant passages with provenance (source, as_of, url).",
                method="POST", path="/rag/search", cost_tier=CostTier.low, markets=["US", "KR"],
                params=[
                    ResourceParam(name="query", required=True, description="Natural-language query."),
                    ResourceParam(name="top_k", type="integer", description="Max passages."),
                    P_TICKER, P_MARKET,
                ],
                provenance=Provenance(source="Platform RAG (filings/news)", freshness=Freshness.periodic),
            ),
        ],
    ),
]


def get_catalog() -> list[ConnectorManifest]:
    return CONNECTORS


def get_connector(connector_id: str) -> ConnectorManifest | None:
    return next((c for c in CONNECTORS if c.id == connector_id), None)


def all_resource_paths(service: str = "datasets") -> set[tuple[str, str]]:
    """(method, path) pairs for connectors served by `service` (default the data plane).
    Other services (e.g. 'rag') are served elsewhere, so their paths are not data-plane routes."""
    return {(r.method.upper(), r.path) for c in CONNECTORS if c.service == service for r in c.resources}
