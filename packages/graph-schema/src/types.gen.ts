/**
 * verified (>=2 independent sources, or exact math from a primary filing) | derived (single disclosure + math) | estimated (algorithmic only).
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "ConfidenceTier".
 */
export type ConfidenceTier = "verified" | "derived" | "estimated";
/**
 * fresh (<~30d) | aging | stale (past next-expected-filing) | gap (no data).
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "Freshness".
 */
export type Freshness = "fresh" | "aging" | "stale" | "gap";
/**
 * Cost-bucket typing used to convert between supplier and customer ledgers.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "CostBucket".
 */
export type CostBucket = "COGS" | "CAPEX" | "R&D" | "SG&A";
/**
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "SourceType".
 */
export type SourceType = "filing" | "IR" | "report" | "news" | "interview";
/**
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "VerificationStatus".
 */
export type VerificationStatus = "unverified" | "verified" | "disputed";

/**
 * Canonical, language-neutral single source of truth for ValueGraph nodes, edges, and claims (PRD v5 §5). Consumed by the TS apps (generated types + ajv validation) and the Python services (TypedDicts + jsonschema validation). Schema-reserved edges REVENUE_FLOW / INVESTS_IN / COMPETES_WITH are intentionally NOT defined in v1.
 */
export interface ValueGraphKnowledgeGraphSchema {
  [k: string]: unknown;
}
/**
 * Every quantified figure ships an interval, never a bare point (PRD §6.2).
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "ConfidenceInterval".
 */
export interface ConfidenceInterval {
  low: number;
  high: number;
}
/**
 * Theme-level mix of confidence tiers, as percentages.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "DataQuality".
 */
export interface DataQuality {
  verified: number;
  derived: number;
  estimated: number;
  gap: number;
}
/**
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "Theme".
 */
export interface Theme {
  name: string;
  depth_max?: number;
  version?: string;
  published_at?: string | null;
  data_quality?: DataQuality;
}
/**
 * A listed company; node size in the Terminal = live market_cap.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "Company".
 */
export interface Company {
  ticker: string;
  name: string;
  country?: string;
  exchange?: string;
  /**
   * Real-time layer (live feed). Not a periodic/disclosure figure.
   */
  market_cap?: number | null;
  /**
   * Real-time layer (live feed).
   */
  price?: number | null;
  sector?: string;
  tier?: number | null;
  fiscal_calendar?: string | null;
  last_filing_date?: string | null;
  next_filing_estimate?: string | null;
}
/**
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "Division".
 */
export interface Division {
  name: string;
  revenue_share?: number | null;
  parent_company?: string | null;
}
/**
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "Product".
 */
export interface Product {
  name: string;
  category?: string | null;
  cost_bucket_hint?: CostBucket | null;
}
/**
 * No number enters the graph without a Source (PRD §4).
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "Source".
 */
export interface Source {
  type: SourceType;
  url: string;
  publisher?: string | null;
  as_of_date: string;
  language?: string | null;
  verification_status?: VerificationStatus;
}
/**
 * One atomic, sourced assertion extracted from a document. No verbatim text_span -> no claim (PRD §6.2 S1).
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "Claim".
 */
export interface Claim {
  relation: string;
  subject: string;
  object: string;
  value?: number | null;
  unit?: string | null;
  cost_bucket?: CostBucket | null;
  as_of: string;
  source_id: string;
  /**
   * Identifier of the extractor (e.g. the Gemini model id / tier).
   */
  extracted_by: string;
  /**
   * Verbatim span the claim was extracted from. Required.
   */
  text_span: string;
}
/**
 * Company -> Division. No attributes in v1.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "HasDivisionEdge".
 */
export interface HasDivisionEdge {}
/**
 * Division -> Product.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "ProducesEdge".
 */
export interface ProducesEdge {
  capacity?: number | null;
  yield?: number | null;
}
/**
 * Core v1 relationship: a supplier -> customer trade. Per PRD §5.3, every quantitative figure MUST carry as_of_date, next_expected_update, confidence + confidence_interval and a derived freshness. trade_value / shares stay nullable so gaps can be drawn rather than hidden.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "SuppliesEdge".
 */
export interface SuppliesEdge {
  /**
   * Supplier company ticker.
   */
  supplier: string;
  /**
   * Customer company ticker.
   */
  customer: string;
  product_ref?: string | null;
  trade_value?: number | null;
  currency?: string | null;
  supplier_rev_share?: number | null;
  customer_cost_share?: number | null;
  cost_bucket?: CostBucket | null;
  confidence: ConfidenceTier;
  confidence_interval: ConfidenceInterval;
  as_of_date: string;
  next_expected_update: string;
  freshness: Freshness;
  gap?: boolean;
}
/**
 * Claim -> SUPPLIES. Whether the claim agrees with the reconciled edge value.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "SupportsEdge".
 */
export interface SupportsEdge {
  weight?: number | null;
  agrees: boolean;
}
/**
 * Claim -> Source.
 *
 * This interface was referenced by `ValueGraphKnowledgeGraphSchema`'s JSON-Schema
 * via the `definition` "SourcedFromEdge".
 */
export interface SourcedFromEdge {
  extracted_value?: number | string | null;
}
