// [M4-PERSIST-01] Versioned theme-build provenance. IF NOT EXISTS keeps re-runs
// idempotent; applied versions are tracked in (:_SchemaMigration) nodes.

// One ThemeBuild node per (theme, version).
CREATE CONSTRAINT theme_build_unique IF NOT EXISTS
FOR (b:ThemeBuild) REQUIRE (b.theme_id, b.version) IS UNIQUE;

// A Source node is uniquely identified by its source_id (shared across builds).
CREATE CONSTRAINT source_id_unique IF NOT EXISTS
FOR (s:Source) REQUIRE s.id IS UNIQUE;

// Claim identity = content hash (the schema Claim has no id field).
CREATE CONSTRAINT claim_key_unique IF NOT EXISTS
FOR (c:Claim) REQUIRE c.key IS UNIQUE;

// Speed build-scoped lookups for reconstruction.
CREATE INDEX claim_build IF NOT EXISTS FOR (c:Claim) ON (c.theme_id, c.build_version);
CREATE INDEX gap_edge_build IF NOT EXISTS FOR (g:GapEdge) ON (g.theme_id, g.build_version);
