# Control-plane image. Deps from the lockfile in a cached layer, then the code.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY controlplane ./controlplane
RUN uv sync --frozen --no-dev

EXPOSE 8001

CMD ["uvicorn", "controlplane.main:app", "--host", "0.0.0.0", "--port", "8001"]
