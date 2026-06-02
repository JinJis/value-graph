// [M0-SCHEMA-03] Scaffold demo proving the canonical @valuegraph/graph-schema types
// import and typecheck from an app. Replaced by real usage in M1+.
import type { ConfidenceTier, SuppliesEdge } from "@valuegraph/graph-schema";

/** Render a one-line label for a SUPPLIES edge (admin debug helper). */
export function describeSuppliesEdge(edge: SuppliesEdge): string {
  const tier: ConfidenceTier = edge.confidence;
  return `${edge.supplier} -> ${edge.customer} [${tier}, ${edge.freshness}]`;
}
