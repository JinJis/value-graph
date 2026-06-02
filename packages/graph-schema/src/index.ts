/**
 * @valuegraph/graph-schema — single source of truth for the knowledge-graph
 * type definitions (Theme / Company / Division / Product / Source / Claim nodes
 * and HAS_DIVISION / PRODUCES / SUPPLIES / SUPPORTS / SOURCED_FROM edges).
 *
 * This is a [M0-REPO-01] scaffold placeholder. The real type defs — consumed by
 * both the TS apps and the Python services — are introduced in [M0-SCHEMA-03].
 */

/** Schema package version; bumped when the canonical type defs change. */
export const SCHEMA_PACKAGE_VERSION = "0.0.0" as const;
