"""Pluggable embedding backends, selected by RAG_EMBEDDING_BACKEND.

All implement ``async embed(texts) -> list[list[float]]`` returning L2-normalized
vectors. Heavy SDKs are imported lazily so the base install stays light.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from functools import cache
from typing import Protocol

import httpx

from rag.config import settings

_TOKEN = re.compile(r"[A-Za-z0-9]+|[가-힣]+")


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


class Embedder(Protocol):
    dim: int
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic bag-of-hashed-tokens — no deps. Lexical, fine for dev/CI."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _TOKEN.findall(text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        return _normalize(v)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class FastEmbedEmbedder:
    """oss-cpu / oss-gpu via fastembed (ONNX, light)."""

    def __init__(self, model: str, cuda: bool = False) -> None:
        from fastembed import TextEmbedding

        providers = ["CUDAExecutionProvider"] if cuda else None
        self._model = TextEmbedding(model_name=model, providers=providers)
        self.dim = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _run() -> list[list[float]]:
            return [_normalize(list(map(float, e))) for e in self._model.embed(texts)]

        out = await asyncio.to_thread(_run)
        if out:
            self.dim = len(out[0])
        return out


class SentenceTransformerEmbedder:
    """oss-gpu (or cpu) via sentence-transformers (torch)."""

    def __init__(self, model: str, device: str = "cuda") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model, device=device)
        self.dim = self._model.get_sentence_embedding_dimension()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _run():
            return self._model.encode(texts, normalize_embeddings=True).tolist()

        return await asyncio.to_thread(_run)


class TEIEmbedder:
    """A remote Text-Embeddings-Inference / Infinity endpoint (typically GPU served)."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.dim = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.post(f"{self.endpoint}/embed", json={"inputs": texts})
            resp.raise_for_status()
            vecs = resp.json()
        out = [_normalize([float(x) for x in v]) for v in vecs]
        if out:
            self.dim = len(out[0])
        return out


class VertexEmbedder:
    """gcp — Vertex AI embeddings (e.g. gemini-embedding-001)."""

    def __init__(self, model: str, project: str, location: str) -> None:
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        vertexai.init(project=project, location=location)
        self._model = TextEmbeddingModel.from_pretrained(model)
        self.dim = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _run() -> list[list[float]]:
            return [_normalize(list(e.values)) for e in self._model.get_embeddings(texts)]

        out = await asyncio.to_thread(_run)
        if out:
            self.dim = len(out[0])
        return out


@cache
def get_embedder() -> Embedder:
    backend = settings.embedding_backend
    if backend == "hash":
        return HashEmbedder(settings.hash_dim)
    if backend == "oss-cpu":
        return FastEmbedEmbedder(settings.embedding_model, cuda=False)
    if backend == "oss-gpu":
        return SentenceTransformerEmbedder(settings.embedding_model, device="cuda")
    if backend == "tei":
        return TEIEmbedder(settings.embedding_endpoint)
    if backend == "gcp":
        model = settings.embedding_model if "embedding" in settings.embedding_model else "gemini-embedding-001"
        return VertexEmbedder(model, settings.gcp_project, settings.gcp_location)
    raise ValueError(f"Unknown RAG_EMBEDDING_BACKEND '{backend}'.")
