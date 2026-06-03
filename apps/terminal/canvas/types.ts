// [M5-CANVAS-01] Shapes of the read-only Production graph the canvas renders.
// Mirrors the engine PublishedGraph (GET /themes/{id}/graph).

export interface GraphCompany {
  ticker: string;
  name: string;
  market_cap?: number | null;
  // ...other Company fields are ignored by the macro map.
}

export interface ConfidenceInterval {
  low: number;
  high: number;
}

export interface GraphEdge {
  supplier: string;
  customer: string;
  product_ref?: string | null;
  trade_value?: number | null;
  currency?: string | null;
  supplier_rev_share?: number | null;
  customer_cost_share?: number | null;
  cost_bucket?: string | null;
  confidence: string; // verified | derived | estimated
  confidence_interval?: ConfidenceInterval;
  freshness: string; // fresh | aging | stale | gap
  as_of_date?: string;
  next_expected_update?: string;
  gap?: boolean;
}

// A Source backing an edge's figures (PROV-02).
export interface SourceRef {
  source_id: string;
  url?: string | null;
  type?: string | null;
  as_of_date?: string | null;
}

export interface GhostEdge {
  supplier: string;
  customer: string;
  confidence: string;
  freshness: string;
  reason: string;
}

export interface PublishedGraph {
  theme_id: string;
  snapshot_version: number;
  completeness: number;
  companies: GraphCompany[];
  edges: GraphEdge[];
  ghost_edges: GhostEdge[];
  // "supplier->customer" -> the Source(s) backing that edge's figures.
  edge_sources: Record<string, SourceRef[]>;
}

export interface ThemeSummary {
  id: string;
  name: string;
}
