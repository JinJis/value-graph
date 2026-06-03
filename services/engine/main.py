"""ValueGraph Engine — FastAPI application (CLAUDE.md §2).

Run with `uvicorn services.engine.main:app --reload` or `python -m services.engine`.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.engine.blueprint.router import router as blueprint_router
from services.engine.feed.router import router as feed_router
from services.engine.jobs.router import router as jobs_router
from services.engine.publish.router import router as publish_router
from services.engine.sources.router import router as sources_router
from services.engine.themes.router import router as themes_router
from services.engine.tickets.router import router as tickets_router
from services.engine.tickets.state import InvalidTransition

app = FastAPI(title="ValueGraph Engine", version="0.0.0")


@app.exception_handler(InvalidTransition)
async def _invalid_transition_handler(_: Request, exc: InvalidTransition) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# Studio (Admin, :3001) and Terminal (User, :3000) run on different origins; allow
# them to call the API directly. By default we accept those two ports on ANY host
# (localhost OR a remote server's IP/hostname), since the apps resolve the engine at
# whatever host they were loaded from. No credentials are used, so this is safe.
# Override with CORS_ORIGINS (comma-separated exact origins, or "*").
_cors_env = os.environ.get("CORS_ORIGINS")
_cors_kwargs: dict[str, object] = (
    {"allow_origins": [o.strip() for o in _cors_env.split(",") if o.strip()]}
    if _cors_env
    else {"allow_origin_regex": r"https?://[^/]+:(3000|3001)"}
)
app.add_middleware(
    CORSMiddleware,
    allow_methods=["*"],
    allow_headers=["*"],
    **_cors_kwargs,  # type: ignore[arg-type]
)

app.include_router(themes_router)
app.include_router(blueprint_router)
app.include_router(tickets_router)
app.include_router(sources_router)
app.include_router(publish_router)
app.include_router(feed_router)
app.include_router(jobs_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Datastore readiness is added in [M0-DB-06]."""
    return {"status": "ok", "service": "engine"}
