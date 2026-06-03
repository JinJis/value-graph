// [M6-DRAWER-01] Build a company's drawer view-model from the published graph: its
// products (grouped by edge product_ref) -> who buys each (+ share), and who supplies
// it. Live price/market cap is sourced separately (real-time, not from filings).

import { edgeKey } from "../canvas/controls";
import type { MarketFeed } from "../canvas/marketFeed";
import type {
  EdgeDetail,
  GraphCompany,
  GraphEdge,
  PublishedGraph,
} from "../canvas/types";
import type { FigureProvenance } from "../provenance/provenance";

export const UNSPECIFIED_PRODUCT = "(unspecified product)";

// Both-ledger shares + the inspector detail for one edge.
export interface EdgeLedgers {
  supplierRevShare: number | null;
  customerCostShare: number | null;
  detail: EdgeDetail | null;
}

function edgeLedgers(
  edge: GraphEdge,
  details: PublishedGraph["edge_details"],
): EdgeLedgers {
  return {
    supplierRevShare: edge.supplier_rev_share ?? null,
    customerCostShare: edge.customer_cost_share ?? null,
    detail: details[edgeKey(edge.supplier, edge.customer)] ?? null,
  };
}

function figureFromEdge(
  edge: GraphEdge,
  value: number | null,
  unit: string,
  sources: PublishedGraph["edge_sources"],
): FigureProvenance {
  return {
    value,
    unit,
    interval: edge.confidence_interval ?? null,
    confidence: edge.confidence,
    freshness: edge.freshness,
    asOf: edge.as_of_date ?? null,
    nextUpdate: edge.next_expected_update ?? null,
    sources: sources[edgeKey(edge.supplier, edge.customer)] ?? [],
  };
}

export interface CustomerLink {
  key: string; // edge key for canvas highlighting
  customer: string;
  customerCostShare: number | null;
  tradeValue: number | null;
  confidence: string;
  freshness: string;
  gap: boolean;
  provenance: FigureProvenance;
  ledgers: EdgeLedgers;
}

export interface ProductGroup {
  product: string;
  edgeKeys: string[]; // all customer edges for this product (canvas highlight)
  customers: CustomerLink[];
}

export interface SupplierLink {
  key: string;
  supplier: string;
  supplierRevShare: number | null;
  confidence: string;
  freshness: string;
  provenance: FigureProvenance;
  ledgers: EdgeLedgers;
}

export interface MarketSnapshot {
  marketCap: number | null;
  live: boolean; // real-time/licensed vs delayed/mock
}

export interface CompanyView {
  ticker: string;
  name: string;
  market: MarketSnapshot;
  products: ProductGroup[]; // outgoing: what this company supplies, by product
  suppliers: SupplierLink[]; // incoming: who supplies this company
}

function customerLink(
  e: GraphEdge,
  sources: PublishedGraph["edge_sources"],
  details: PublishedGraph["edge_details"],
): CustomerLink {
  const share = e.customer_cost_share ?? null;
  return {
    key: edgeKey(e.supplier, e.customer),
    customer: e.customer,
    customerCostShare: share,
    tradeValue: e.trade_value ?? null,
    confidence: e.confidence,
    freshness: e.freshness,
    gap: e.gap ?? false,
    provenance: figureFromEdge(e, share, "% of cost", sources),
    ledgers: edgeLedgers(e, details),
  };
}

function groupByProduct(
  edges: GraphEdge[],
  sources: PublishedGraph["edge_sources"],
  details: PublishedGraph["edge_details"],
): ProductGroup[] {
  const groups = new Map<string, ProductGroup>();
  for (const e of edges) {
    const product = e.product_ref ?? UNSPECIFIED_PRODUCT;
    let g = groups.get(product);
    if (!g) {
      g = { product, edgeKeys: [], customers: [] };
      groups.set(product, g);
    }
    g.customers.push(customerLink(e, sources, details));
    g.edgeKeys.push(edgeKey(e.supplier, e.customer));
  }
  return [...groups.values()];
}

export function buildCompanyView(
  graph: PublishedGraph,
  ticker: string,
  feed: MarketFeed,
): CompanyView | null {
  const company: GraphCompany | undefined = graph.companies.find(
    (c) => c.ticker === ticker,
  );
  if (!company) return null;

  const outgoing = graph.edges.filter((e) => e.supplier === ticker);
  const incoming = graph.edges.filter((e) => e.customer === ticker);

  return {
    ticker,
    name: company.name,
    market: {
      marketCap: company.market_cap ?? feed.marketCap(ticker),
      live: feed.live,
    },
    products: groupByProduct(outgoing, graph.edge_sources, graph.edge_details),
    suppliers: incoming.map((e) => ({
      key: edgeKey(e.supplier, e.customer),
      supplier: e.supplier,
      supplierRevShare: e.supplier_rev_share ?? null,
      confidence: e.confidence,
      freshness: e.freshness,
      provenance: figureFromEdge(
        e,
        e.supplier_rev_share ?? null,
        "% of rev",
        graph.edge_sources,
      ),
      ledgers: edgeLedgers(e, graph.edge_details),
    })),
  };
}

export function formatMarketCap(cap: number | null): string {
  if (!cap || cap <= 0) return "—";
  if (cap >= 1e12) return `$${(cap / 1e12).toFixed(2)}T`;
  if (cap >= 1e9) return `$${(cap / 1e9).toFixed(1)}B`;
  if (cap >= 1e6) return `$${(cap / 1e6).toFixed(0)}M`;
  return `$${cap.toFixed(0)}`;
}
