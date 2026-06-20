# RAG Service

Provenance-first retrieval over the platform's documents (filings, news, transcripts). The pipeline —
**chunk → embed → vector store → retrieve → (optional) rerank** — keeps a **provenance envelope on every
chunk** (source, doc_type, ticker, as_of, url, section…), so retrieved passages are citeable and
consistent with the structured connector data.

Embedding / reranker / vector store are **pluggable backends selected by `.env`** — flip between
**CPU-OSS / GCP / GPU** with no code change:

| Tier | `RAG_EMBEDDING_BACKEND` | What runs |
|---|---|---|
| CPU + open-source | `oss-cpu` | fastembed (ONNX) on CPU — e.g. `BAAI/bge-m3` (extra: `oss`) |
| Google Cloud | `gcp` | Vertex AI `gemini-embedding-001` (extra: `gcp`) |
| GPU instance | `oss-gpu` | sentence-transformers on CUDA (extra: `st`) |
| GPU (served) | `tei` | a remote Text-Embeddings-Inference endpoint (`RAG_EMBEDDING_ENDPOINT`) |
| dev / CI | `hash` | deterministic, dependency-free (default) |

Reranker (`RAG_RERANKER_BACKEND`): `none` · `oss-cpu`/`oss-gpu` (BGE-reranker-v2-m3) · `tei` ·
`gcp` (Vertex AI Ranking API). Vector store (`RAG_VECTOR_STORE`): `memory` (dev) · `pgvector` (prod).

## Run

```bash
cd platform/rag
uv sync --extra dev                 # base (hash + memory) — runs anywhere
# pick a real backend:
#   uv sync --extra oss   && export RAG_EMBEDDING_BACKEND=oss-cpu
#   uv sync --extra gcp   && export RAG_EMBEDDING_BACKEND=gcp RAG_GCP_PROJECT=...
#   uv sync --extra st    && export RAG_EMBEDDING_BACKEND=oss-gpu
uv run uvicorn rag.main:app --reload --port 8002
uv run pytest -q
```

```bash
curl -X POST localhost:8002/rag/ingest -H 'Content-Type: application/json' -d '{
  "documents":[{"text":"Apple relies on a limited number of suppliers including TSMC...","source":"SEC EDGAR","doc_type":"10-K","ticker":"AAPL","url":"https://sec.gov/..."}]}'
curl -X POST localhost:8002/rag/search -H 'Content-Type: application/json' -d '{"query":"Apple chip suppliers","top_k":3}'
curl localhost:8002/rag/info     # which backends are active
```

Every hit returns `{text, score, provenance}` — provenance carries the source + as_of + url so agents cite it.
