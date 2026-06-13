# Platform — Investment-Agent Data Platform

> A fresh start. This workspace is the **new service**, built up from the `datasets/` data API.
> **The legacy ValueGraph engine (`/services`, `/apps`, CVE, Deep-Research data acquisition) is treated
> as nonexistent** — none of it is a dependency here.

The goal: a **multi-tenant platform for investment agents** — a data-source layer that tenants activate
to their needs, exposed as a **REST API, an MCP server, a RAG server, and an Agent Engine**, where
builders develop against a defined interface or via natural language.

## Layout

```
platform/
  datasets/        # ✅ DATA PLANE — US+KR financial data API (the foundation; built & tested)
                   #    connectors (SEC/DART/Yahoo/FRED/ECOS/news) · point-in-time ingestion store
                   #    · bulk/deep backfill · scheduler · self-test · catalog manifests (P0, in progress)
  # planned, built on top of datasets/:
  # control-plane/ # tenants · scoped API keys · source activation/entitlements · metering · governance
  # mcp/           # MCP server — tenant-scoped tools auto-derived from connector manifests
  # rag/           # document ingestion + Gemini embeddings + pgvector retrieval (provenance-first)
  # agent-engine/  # build & run agents (SDK + natural language) over activated sources
  # value-chain/   # flagship: a user-cloneable supplier→customer value-chain agent
```

## Principles

- **Deterministic connectors + RAG, not Deep Research** — data is structured, fast, reproducible,
  citeable. Deep Research is at most one optional tool.
- **Provenance/trust envelope everywhere** — every datum/chunk/agent output carries source + as-of +
  freshness (+ confidence where derivable). No number without a source.
- **Platform holds upstream keys, meters usage, bills tenants** — so a per-connector license /
  redistribution policy is mandatory (SEC/DART/FRED are redistribution-safe; restricted feeds use
  BYO-key).
- **One Gemini router, one tenancy model** — don't fork.

## Roadmap

`datasets/` is live (see `datasets/README.md`). Next: **P0** connector manifests + catalog (in
`datasets/`) → **P1** control plane → **P2** MCP server → **P3** RAG → **P4** Agent Engine, with the
**value-chain agent** as the flagship template.

## Run the data plane

```bash
cd datasets
uv sync --extra dev
uv run uvicorn app.main:app --reload     # /docs
uv run pytest -q
```
