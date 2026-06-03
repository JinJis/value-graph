"""[M3-ORCH-08] PostgresCveRunRepository against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations through 0008 applied).
"""

from __future__ import annotations

import os

import pytest

from services.engine.cve.run_repository import DONE, RUNNING, PostgresCveRunRepository
from services.engine.db.config import DbSettings
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def test_cve_run_persists_and_reconstructs() -> None:
    settings = DbSettings.from_env()
    themes = PostgresThemeRepository(settings)
    runs = PostgresCveRunRepository(settings)

    theme = themes.create_theme(ThemeCreate(name="CVE RUN DBTEST"))

    started = runs.start(theme.id, "admin")
    assert started.status == RUNNING and started.trigger == "admin"

    state = {"edges": {"A->B": {"target": "A->B"}}, "claims": [], "resolutions": []}
    finished = runs.finish(started.id, status=DONE, state=state)
    assert finished is not None and finished.status == DONE
    # Full intermediate state round-trips out of jobs.payload.
    assert finished.state == state

    fetched = runs.get(started.id)
    assert fetched is not None and fetched.state["edges"]["A->B"]["target"] == "A->B"

    latest = runs.get_latest(theme.id)
    assert latest is not None and latest.id == started.id
