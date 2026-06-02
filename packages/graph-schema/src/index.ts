/**
 * @valuegraph/graph-schema — single source of truth for the knowledge-graph
 * type definitions (PRD §5).
 *
 * Canonical definition: `schema/valuegraph.schema.json` (JSON Schema 2020-12).
 * The TS types below are generated from it (`pnpm --filter @valuegraph/graph-schema
 * run generate`) so they never drift. Runtime validators live in the Node-only
 * subpath `@valuegraph/graph-schema/validate`; the main entry is types only and is
 * safe to import from browser bundles via `import type`.
 */
export type * from "./types.gen.js";
