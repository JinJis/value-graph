# ValueGraph Engine (FastAPI). Build context = repo root (monorepo: the engine
# depends on the graph-schema workspace member).
#   docker build -f services/engine/Dockerfile -t valuegraph-engine .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (better layer caching). The graph-schema workspace
# member (and its bundled schema) must be present for `uv sync` to resolve it.
COPY pyproject.toml uv.lock ./
COPY packages/graph-schema ./packages/graph-schema
RUN uv sync --no-dev --frozen

# App source last — changes here don't bust the dependency layer.
COPY services ./services

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "services.engine.main:app", "--host", "0.0.0.0", "--port", "8000"]
