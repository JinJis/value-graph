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
| Control plane (tenancy, entitlements, gateway, metering) | `control-plane/` | ✅ P1 | 12 |
| MCP server (tools from catalog) | `mcp/` | ✅ P2 | 9 |
| RAG (pluggable CPU-OSS / GCP / GPU; routed via gateway + MCP) | `rag/` | ✅ P3 | 14 |
| Agent Engine (tools + RAG via gateway, guardrails, citations, streaming chat) | `agent-engine/` | ✅ P4 | 21 |
| Studio API (provisioning, conversations, chat BFF, **agent builder**, **prompt library**) | `studio-api/` | ✅ | 24 |
| Web — chat UI + **agent builder** + **prompt library** (Next.js + Auth.js Google) | `web/` | ✅ F1·F2 | build |
| **End-to-end** (full stack via compose, incl. chat) | `scripts/e2e.sh` | ✅ | — |

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
  agent-engine/    # ✅ AGENT ENGINE — run/stream agents over activated connectors + RAG via the gateway;
                   #    guardrails (no advice/forecasting) + provenance citations; stub|gemini planner (P4)
  studio-api/      # ✅ STUDIO API — Google user→tenant provisioning, conversations, chat BFF (holds the key)
  web/             # ✅ WEB — chat UI (Next.js + Auth.js); tools & sources panel + agent builder (F1)
                   #    + prompt library / community import (F2)
  # next phase: Telegram/Slack messengers (F3)
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
cp .env.example .env          # fill in free keys (OPENDART/ECOS/FRED); AUTH_DEV_LOGIN=true for local login
docker compose up --build     # whole stack: datasets :8000 · gateway :8010 · web UI :3000
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
cd agent-engine  && uv sync --extra dev && uv run pytest -q   # Agent Engine (:8003); stub|gemini planner
cd studio-api    && uv sync --extra dev && uv run pytest -q   # Studio API / chat BFF (:8004)
cd web           && npm install && npm run build              # Web UI (:3000)
bash scripts/e2e.sh                                           # full-stack e2e via docker compose
```

All **143 unit tests** pass (web verified via build); `scripts/e2e.sh` exercises the whole chain (catalog
→ tenant → entitlement → data plane + RAG via gateway → metering → MCP → agent → **studio-api chat** →
**agent builder** restricting a chat to a data-source subset → **prompt library** community import).

## The product (chat UI)

```bash
cd platform
cp .env.example .env                       # AUTH_DEV_LOGIN=true for local login without Google
docker compose up --build                  # whole stack incl. web on :3000
# open http://localhost:3000 — ask "삼성전자 최근 실적"; the agent answers with sources.
```
The browser never holds a platform key: web BFF (Auth.js session) → studio-api (holds the tenant key) →
agent-engine → tools via the metered gateway. Guardrails refuse advice/forecasting. For real token
streaming set `AGENT_LLM_BACKEND=gemini` + `GOOGLE_API_KEY`.
