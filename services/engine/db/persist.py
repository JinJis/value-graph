"""[M4-PERSIST-01] Persist a finished CVE run as the next versioned theme build.

The single entry point that guarantees a CVE run's output lives durably in the
graph (nothing important stays only in memory): allocate the next build version,
map the run state into schema-valid artifacts, and save the build.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from services.engine.cve.pipeline import CVEState
from services.engine.db.artifacts import ThemeBuild, build_from_cve
from services.engine.db.graph_store import GraphStore


def persist_cve_run(
    state: CVEState,
    store: GraphStore,
    *,
    sources: list[dict[str, Any]] | None = None,
    company_meta: dict[str, dict[str, Any]] | None = None,
    created_at: datetime | None = None,
) -> ThemeBuild:
    """Map ``state`` to a :class:`ThemeBuild` at the theme's next version and save it."""
    version = store.next_version(state.theme_id)
    build = build_from_cve(
        state,
        version=version,
        sources=sources,
        company_meta=company_meta,
        created_at=created_at,
    )
    return store.save_build(build)
