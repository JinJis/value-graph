# ValueGraph Datasets API — production image.
# Uses the official uv image; deps are installed from the lockfile in a cached
# layer before the app code is copied, so code-only changes rebuild fast.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# 1) dependency layer (no project, no dev deps) — cached unless the lock changes
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# 2) app code + install the project itself
COPY app ./app
COPY openapi.json ./openapi.json
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Configure upstream keys at runtime via -e / --env-file (never baked into the image).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
