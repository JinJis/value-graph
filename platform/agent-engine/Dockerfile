# Agent Engine image (stub planner by default; add the `gemini` extra for the LLM planner).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY agentengine ./agentengine
RUN uv sync --frozen --no-dev

EXPOSE 8003

CMD ["uvicorn", "agentengine.main:app", "--host", "0.0.0.0", "--port", "8003"]
