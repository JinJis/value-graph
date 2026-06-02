"""Apply all ValueGraph database migrations.

    python -m services.engine.db.migrate

Reads connection settings from env (DATABASE_URL, NEO4J_URI/USER/PASSWORD).
"""

from __future__ import annotations

import logging

from services.engine.db import graph, postgres
from services.engine.db.config import DbSettings

logger = logging.getLogger("valuegraph.engine.db.migrate")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = DbSettings.from_env()

    with postgres.connect(settings) as conn:
        pg_applied = postgres.apply_migrations(conn)
    logger.info("postgres migrations applied: %s", pg_applied or "none (up to date)")

    driver = graph.connect(settings)
    try:
        neo_applied = graph.apply_constraints(driver)
    finally:
        driver.close()
    logger.info("neo4j migrations applied: %s", neo_applied or "none (up to date)")


if __name__ == "__main__":
    main()
