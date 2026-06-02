// [M0-DB-06] Neo4j constraints. IF NOT EXISTS makes re-runs idempotent; the runner
// also tracks applied versions in (:_SchemaMigration) nodes.

// A Company node is uniquely identified by its ticker (PRD §5; one node per ticker).
CREATE CONSTRAINT company_ticker_unique IF NOT EXISTS
FOR (c:Company) REQUIRE c.ticker IS UNIQUE;
