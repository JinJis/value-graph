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
# them to call the API directly. Override with CORS_ORIGINS (comma-separated).
_default_origins = "http://localhost:3001,http://localhost:3000"
_cors_origins = os.environ.get("CORS_ORIGINS", _default_origins).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _cors_origins if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(themes_router)
app.include_router(blueprint_router)
app.include_router(tickets_router)
app.include_router(sources_router)
app.include_router(publish_router)
app.include_router(feed_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Datastore readiness is added in [M0-DB-06]."""
    return {"status": "ok", "service": "engine"}
