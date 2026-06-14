"""RAG settings — every backend is selectable via env (RAG_* in the shared .env).

Three performance tiers, all behind the same interface:
  * oss-cpu  — open-source ONNX embeddings on CPU (fastembed)        [extra: oss]
  * oss-gpu  — open-source on a GPU instance (sentence-transformers) [extra: st]
  * gcp      — Vertex AI gemini-embedding-001 + Ranking API          [extra: gcp]
  * tei      — a remote Text-Embeddings-Inference endpoint (GPU served)
  * hash     — deterministic, dependency-free (dev/CI default)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- embeddings --------------------------------------------------------
    embedding_backend: str = "oss-cpu"          # hash | oss-cpu | oss-gpu | tei | gcp
    embedding_model: str = "BAAI/bge-m3"
    embedding_endpoint: str = ""             # for tei
    hash_dim: int = 384

    # --- reranker ----------------------------------------------------------
    reranker_backend: str = "none"           # none | oss-cpu | oss-gpu | tei | gcp
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_endpoint: str = ""

    # --- vector store ------------------------------------------------------
    vector_store: str = "pgvector"             # memory | pgvector
    database_url: str = ""                    # pgvector (postgresql://...)

    # --- google cloud ------------------------------------------------------
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    gcp_ranking_config: str = "default_ranking_config"

    # --- retrieval ---------------------------------------------------------
    top_k: int = 8
    rerank_top_n: int = 5
    http_timeout_seconds: float = 60.0


settings = Settings()
