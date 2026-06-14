# RAG service image. Ships the `oss` extra (fastembed/ONNX) so a real semantic
# embedder (RAG_EMBEDDING_BACKEND=oss-cpu) works in the container — the default
# stays `hash` (deterministic, no model download) and is flipped via .env.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev --extra oss

COPY rag ./rag
RUN uv sync --frozen --no-dev --extra oss

EXPOSE 8002

CMD ["uvicorn", "rag.main:app", "--host", "0.0.0.0", "--port", "8002"]
