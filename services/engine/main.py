"""ValueGraph Engine — FastAPI application (CLAUDE.md §2).

[M0-API-05] skeleton: a liveness `/health` endpoint. CVE, blueprint, publish, etc.
are added in later milestones. Run with `uvicorn services.engine.main:app --reload`
or `python -m services.engine`.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="ValueGraph Engine", version="0.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Datastore readiness is added in [M0-DB-06]."""
    return {"status": "ok", "service": "engine"}
