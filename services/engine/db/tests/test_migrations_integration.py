"""[M0-DB-06] Integration: live Postgres + Neo4j migrations and the unique-ticker
constraint.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires the infra stack up) so the default test
suite stays green without Docker.
"""

from __future__ import annotations

import os

import pytest
from neo4j.exceptions import ClientError

from services.engine.db import graph, postgres
from services.engine.db.config import DbSettings

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres + Neo4j up) to run DB integration tests",
)

PG_TABLES = ["users", "themes_meta", "tickets", "jobs", "disclosure_calendar", "schema_migrations"]


def test_postgres_migrations_idempotent_and_tables_exist() -> None:
    settings = DbSettings.from_env()
    with postgres.connect(settings) as conn:
        postgres.apply_migrations(conn)  # settle to a known state
        assert postgres.apply_migrations(conn) == []  # re-run is a no-op (idempotent)
        with conn.cursor() as cur:
            for table in PG_TABLES:
                cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                row = cur.fetchone()
                assert row is not None and row[0] is not None, f"missing table: {table}"


def test_neo4j_unique_ticker_enforced() -> None:
    settings = DbSettings.from_env()
    driver = graph.connect(settings)
    ticker = "ZZ_DBTEST_DUP"
    try:
        graph.apply_constraints(driver)
        assert graph.apply_constraints(driver) == []  # idempotent re-run
        with driver.session() as session:
            session.run("MATCH (c:Company {ticker: $t}) DETACH DELETE c", t=ticker).consume()
            session.run("CREATE (c:Company {ticker: $t, name: 'A'})", t=ticker).consume()
            try:
                with pytest.raises(ClientError):
                    session.run("CREATE (c:Company {ticker: $t, name: 'B'})", t=ticker).consume()
            finally:
                session.run("MATCH (c:Company {ticker: $t}) DETACH DELETE c", t=ticker).consume()
    finally:
        driver.close()
