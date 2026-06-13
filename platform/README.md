# Platform — Investment-Agent Data Platform

> A fresh start. This workspace is the **new service**, built up from the `datasets/` data API.
> **The legacy ValueGraph engine (`/services`, `/apps`, CVE, Deep-Research data acquisition) is treated
> as nonexistent** — none of it is a dependency here.

The goal: a **multi-tenant platform for investment agents** — a data-source layer that tenants activate
to their needs, exposed as a **REST API, an MCP server, a RAG server, and an Agent Engine**, where
builders develop against a defined interface or via natural language.

📖 **Docs:** [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) (detailed design + progress) ·
[`docs/ROADMAP.md`](./docs/ROADMAP.md) (task tracker / what's next).

## Status

| Component | Path | Status | Tests |
|---|---|---|---|
| Data plane (US+KR financial API) | `datasets/` | ✅ | 63 |
| Connector catalog/manifests (P0) | `datasets/app/connectors/` | ✅ | — |
| Control plane (tenancy, entitlements, gateway, metering) | `control-plane/` | ✅ P1 | 8 |
| MCP server (tools from catalog) | `mcp/` | ✅ P2 | 6 |
| RAG (pluggable CPU-OSS / GCP / GPU; routed via gateway + MCP) | `rag/` | ✅ P3 | 9 |
| **End-to-end** (full stack via compose) | `scripts/e2e.sh` | ✅ | — |
| Agent Engine | `agent-engine/` | ⬜ P4 | — |
| Value-chain flagship | `value-chain/` | ⬜ | — |

## Layout

```
platform/
  datasets/        # ✅ DATA PLANE — US+KR financial data API (the foundation; built & tested)
                   #    connectors (SEC/DART/Yahoo/FRED/ECOS/news) · point-in-time ingestion store
                   #    · bulk/deep backfill · scheduler · self-test · catalog manifests (P0)
  control-plane/   # ✅ CONTROL PLANE — tenants · scoped API keys · connector activation/entitlements
                   #    · metering · audit · rate-limit · gateway in front of the data plane (P1)
  mcp/             # ✅ MCP SERVER — tenant-scoped tools auto-derived from the catalog, routed through
                   #    the gateway with the tenant key (entitlement + metering enforced) (P2)
  rag/             # ✅ RAG SERVICE — provenance-first chunk→embed→store→retrieve→rerank, with
                   #    pluggable backends (CPU-OSS / GCP-Vertex / GPU) selected by .env (P3)
  # planned, built on top of datasets/:
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

P0–P3 are built (see the status table above). **Next: P4 Agent Engine**, then the **value-chain**
flagship. Full task tracker in [`docs/ROADMAP.md`](./docs/ROADMAP.md).

## Run the whole stack (one command)

A single `docker compose` brings up the data plane + control plane, both reading **one shared
`platform/.env`** (copy from `.env.example`):

```bash
cd platform
cp .env.example .env          # fill in free keys (OPENDART/ECOS/FRED)
docker compose up --build     # datasets on :8000, control-plane gateway on :8010
docker compose down
```

Then drive it through the gateway (control-plane on host `:8010`):
```bash
A='-H X-Admin-Token:dev-admin-token'
PRJ=...   # POST /admin/tenants -> /projects -> /keys -> /activations (connector_id)
curl -H "X-API-KEY: vgk_..." "http://127.0.0.1:8010/company/facts?ticker=AAPL&market=US"
```

Local (no docker): run each with `uv run uvicorn ...`; both still read the shared `../.env`.

## Run / test each service

Each service is a `uv` project with its own README and tests:

```bash
cd datasets      && uv sync --extra dev && uv run pytest -q   # data plane (:8000, /docs)
cd control-plane && uv sync --extra dev && uv run pytest -q   # gateway (:8001/:8010)
cd mcp           && uv sync --extra dev && uv run pytest -q   # MCP server (stdio)
cd rag           && uv sync --extra dev && uv run pytest -q   # RAG (:8002); flip backend in .env
bash scripts/e2e.sh                                           # full-stack e2e via docker compose
```

All **86 unit tests** pass; `scripts/e2e.sh` exercises the whole chain (catalog → tenant → entitlement
→ data plane + RAG via gateway → metering → MCP) on the composed stack. See each service's `README.md`.
