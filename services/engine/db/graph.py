"""Neo4j connection + constraint runner (Cypher under infra/migrations/neo4j).

Named ``graph`` rather than ``neo4j`` to avoid shadowing the ``neo4j`` package.
"""

from __future__ import annotations

from pathlib import Path

from neo4j import Driver, GraphDatabase

from services.engine.db.config import DbSettings
from services.engine.db.planning import discover, plan, split_statements

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "infra" / "migrations" / "neo4j"


def connect(settings: DbSettings) -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )


def apply_constraints(driver: Driver, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending Neo4j migrations; return the versions applied this run.

    Idempotent: applied versions are tracked in (:_SchemaMigration) nodes and skipped.
    """
    discovered = discover(directory, "*.cypher")
    with driver.session() as session:
        result = session.run("MATCH (m:_SchemaMigration) RETURN m.version AS version")
        applied = {str(record["version"]) for record in result}
        pending = plan(discovered, applied)
        for migration in pending:
            for statement in split_statements(migration.body):
                session.run(statement).consume()
            session.run(
                "MERGE (m:_SchemaMigration {version: $version})",
                version=migration.version,
            ).consume()
    return [migration.version for migration in pending]
