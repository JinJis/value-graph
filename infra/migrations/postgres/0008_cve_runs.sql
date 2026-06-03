-- [M3-ORCH-08] CVE runs reuse the existing `jobs` table (type='cve_run'): the
-- full intermediate CVEState is persisted in jobs.payload so a run is fully
-- reconstructable. This index speeds "latest run for a theme" lookups. The
-- versioned per-build graph persistence (Neo4j nodes/edges/claims) lands in
-- M4-PERSIST-01; here we persist the orchestration state only.

CREATE INDEX IF NOT EXISTS idx_jobs_type_theme ON jobs (type, theme_id, created_at DESC);
