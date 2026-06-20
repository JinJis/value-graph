# Agent Engine image. Ships the `gemini` extra so AGENT_LLM_BACKEND=gemini works
# out of the box (the stub planner stays the default and needs no key).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev --extra gemini

COPY agentengine ./agentengine
RUN uv sync --frozen --no-dev --extra gemini

EXPOSE 8003

CMD ["uvicorn", "agentengine.main:app", "--host", "0.0.0.0", "--port", "8003"]
