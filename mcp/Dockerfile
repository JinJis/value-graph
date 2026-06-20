# MCP server image. Normally runs over stdio; in CI/e2e it's also used as a
# one-off (`docker compose run --rm mcp python ...`) to exercise the tools against
# the gateway from inside the compose network — so no host `uv` is needed.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY mcpserver ./mcpserver
RUN uv sync --frozen --no-dev

# Default: run the stdio MCP server. e2e overrides the command.
CMD ["python", "-m", "mcpserver.server"]
