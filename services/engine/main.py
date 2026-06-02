"""ValueGraph Engine — FastAPI application (CLAUDE.md §2).

Run with `uvicorn services.engine.main:app --reload` or `python -m services.engine`.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.engine.themes.router import router as themes_router

app = FastAPI(title="ValueGraph Engine", version="0.0.0")

# Studio (Admin) runs on a different origin; allow it to call the API directly.
# Override with CORS_ORIGINS (comma-separated).
_cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3001").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _cors_origins if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(themes_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Datastore readiness is added in [M0-DB-06]."""
    return {"status": "ok", "service": "engine"}
