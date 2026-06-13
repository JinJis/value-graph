# Platform Architecture & Progress

> Detailed design + current state of the **Investment-Agent Data Platform**.
> Companion: [`ROADMAP.md`](./ROADMAP.md) (what's next). Entry point: [`../README.md`](../README.md).

---

## 1. Vision

A **multi-tenant platform for investment agents**: a data-source layer that each tenant activates to
their needs, exposed through four surfaces over one core —

- **REST** (the data plane API)
- **MCP server** (agents call data as tools)
- **RAG server** (retrieval over unstructured filings/news with provenance)
- **Agent Engine** (build/run agents via SDK or natural language) — *planned (P4)*

Builders develop against a defined interface **or** describe what they want in natural language and it
runs over the data sources they've activated. The flagship use case — supplier→customer **value-chain**
mapping — becomes a *user-cloneable agent template*, not a hardwired product.

**Reframe:** the legacy ValueGraph engine (`/services`, `/apps`, CVE, Deep-Research data acquisition) is
**excluded as a dependency**. We mine it for only two generic ideas (a Gemini router, the provenance
schema) and otherwise start fresh from `platform/datasets/`.

---

## 2. Layered architecture

```
                       platform/  (this workspace)
   Builders / Agents ─▶  REST · MCP · RAG · Agent Engine(P4)
                         ─────────────────────────────────────────────────
   control-plane/        Tenants · Projects · scoped API keys · Source catalog
                         Activations/entitlements · metering · audit · rate-limit
                         gateway (auth → entitle → meter → proxy)
                              │
   datasets/ (DATA PLANE)     │            rag/ (RAG SERVICE)
   connectors + ingestion store            chunk→embed→store→retrieve→rerank
   (SEC/DART/Yahoo/FRED/ECOS/news)          pluggable backends (CPU-OSS/GCP/GPU)
                              └──────── shared infra: Postgres · Redis · Vector DB ────────┘
   (legacy services/engine + apps/* = separate existing product, NOT a dependency)
```

---

## 3. Core principles

1. **Deterministic connectors + RAG, not Deep Research** — data is structured, fast, reproducible,
   citeable. Deep Research is at most one optional tool, never the backbone.
2. **Provenance / trust envelope everywhere** — every datum, chunk, and (eventually) agent output
   carries `source` + `as_of` + `freshness` (+ `confidence` where derivable). No number without a source.
3. **Platform-managed keys + metering/billing** → a **per-connector license / redistribution policy is
   mandatory** (SEC/DART/FRED redistribution-safe; Yahoo/news restricted → BYO-key).
4. **One router, one tenancy model** — don't fork the LLM router or auth across services.
5. **Honesty over fake data** — unbuilt endpoints return `501`; gaps are surfaced, never fabricated.

---

## 4. Components (current state)

### 4.1 Data plane — `platform/datasets/`  ✅
A financialdatasets.ai-compatible API extended to Korea. Market chosen with `market=US|KR`.

- **Connectors (provider adapters + registry):** SEC EDGAR (US fundamentals/filings/earnings/insider/13F),
  Yahoo Finance (US+KR prices), FRED (US macro), OpenDART (KR fundamentals/filings/earnings/insider),
  BOK ECOS (KR macro), Google News (US+KR). Free/open defaults; paid adapters behind env keys.
- **Endpoints (real):** company facts, prices + snapshot, 3 financial statements (+ combined), filings,
  macro interest rates, financial-metrics snapshot, news, earnings, insider-trades, 13F (filer_cik),
  screener + line-items.
- **Ingestion store (`app/store/`):** SQLAlchemy point-in-time / restatement-aware `FinancialFact`
  (SQLite default, Postgres via `DATABASE_URL`). Backs the screener and deep history.
- **Bulk / deep backfill (`app/store/bulk.py`):** every annual+quarterly period from companyfacts
  (AAPL → 2007), full-universe via streaming SEC `companyfacts.zip`, KR via DART.
- **Scheduler (`app/scheduler.py`):** periodic refresh; `SCHEDULER_DEEP` for deep backfill;
  monitor/control at `/admin/scheduler`.
- **Self-test (`/admin/selftest`):** runs implemented endpoints in-process → pass/fail/skipped.
- **Catalog (P0, `app/connectors/`):** each connector publishes a **manifest** (resources, params,
  output schema, provenance, freshness, cost tier, required credential, **license policy**). `GET /catalog`.
- **Unbuilt endpoints** are grouped under a `🚧 Not Implemented (501)` tag in `/docs`.
- **62 tests.**

### 4.2 Control plane — `platform/control-plane/`  ✅ (P1)
A gateway in front of the data plane. Package `controlplane` (talks to data plane over HTTP).

- **Store:** `Tenant → Project → ApiKey` (sha256-hashed, prefix lookup) + `Activation` (per-connector
  entitlement) + `UsageEvent` (metering) + `AuditLog`. SQLite default.
- **Entitlement:** fetches the data-plane `/catalog`, maps `(method, path, market)` → connector(s); a
  request is allowed iff the project activated one of them.
- **Gateway flow:** authenticate → entitle → rate-limit → proxy to data plane → meter + audit. Returns
  `x-connector` / `x-cost-units` headers; public `/catalog` passthrough.
- **Admin (X-Admin-Token):** create tenant/project/key, activate connectors, usage + audit summaries.
- **6 tests.** Verified live: activate `yahoo` → `/prices` 200; unactivated → 403; usage metered.

### 4.3 MCP server — `platform/mcp/`  ✅ (P2)
Exposes connectors to agents as MCP tools (official `mcp` SDK, stdio). Package `mcpserver`.

- **Tool generation:** one tool per catalog resource (`{connector}__{resource}`), input schema from
  manifest params, description carries **provenance source + license** (NO-REDISTRIBUTE flag).
- **Execution:** routes through the control-plane gateway with the tenant's `MCP_API_KEY`, so
  entitlement + metering + audit apply. Unactivated connector → gateway 403 in the tool result.
- **Config:** per tenant in the MCP client (`MCP_GATEWAY_URL`, `MCP_API_KEY`).
- **4 tests.** Verified live: 28 tools; `yahoo__prices` (activated) → real data; `sec_edgar__*` → 403.

### 4.4 RAG service — `platform/rag/`  ✅ (P3)
Provenance-first retrieval: **chunk → embed → vector store → retrieve → (optional) rerank**. Package `rag`.

- **Every chunk carries provenance** (source/doc_type/ticker/market/as_of/url/section/accession) → hits
  are citeable and consistent with connector data.
- **Pluggable backends via `RAG_*` env** (CPU-OSS / GCP / GPU, all behind one interface):

  | Part | env | options |
  |---|---|---|
  | embedding | `RAG_EMBEDDING_BACKEND` | `hash` (dev) · `oss-cpu` (fastembed ONNX) · `oss-gpu` (sentence-transformers CUDA) · `tei` (served) · `gcp` (Vertex `gemini-embedding-001`) |
  | reranker | `RAG_RERANKER_BACKEND` | `none` · `oss-cpu`/`oss-gpu` (BGE-reranker-v2-m3) · `tei` · `gcp` (Vertex Ranking API) |
  | vector store | `RAG_VECTOR_STORE` | `memory` (dev) · `pgvector` (prod) |

- **Endpoints:** `/rag/ingest`, `/rag/search` (hits + provenance), `/rag/info`.
- **Component approach** (we keep chunking + provenance) chosen over managed Vertex Search / RAG Engine,
  so the trust envelope stays uniform across structured + unstructured data.
- **6 tests** on the dependency-free default. Verified live: real `oss-cpu` fastembed semantic search.

### 4.5 Keystone — the Connector Manifest
A machine-readable descriptor per connector (`platform/datasets/app/connectors/`). One artifact drives:
REST docs · **MCP tool generation** · RAG source registration · entitlements (activation) · metering
(cost tier) · governance (license policy). An integrity test asserts every manifest path is a real route.

---

## 5. Multi-tenancy, governance & licensing

- **Tenancy:** Tenant → Project → scoped API key; activation per connector is the entitlement unit.
- **Metering/billing:** every gated call writes a `UsageEvent` with cost units by connector tier.
- **Governance (critical, platform-managed keys + redistribution):** each connector carries a
  `license.redistribution` flag (yahoo + news = false). The catalog exposes it; the control plane is the
  enforcement point. **Open item:** wire redistribution enforcement + BYO-key fallback + professional
  legal review before external multi-tenant use.

---

## 6. Deployment

- **One command:** `cd platform && docker compose up --build` → data plane (`:8000`) + control-plane
  gateway (`:8010`), both reading **one shared `platform/.env`** (compose `env_file`).
- **Single env:** every service reads `env_file=("../.env", ".env")` — shared `platform/.env` first,
  optional per-service override. `platform/.env` is gitignored; `.env.example` is the template.
- **Stores:** SQLite by default (persistent compose volumes); `DATABASE_URL` → Postgres in prod.
- MCP runs over stdio (launched by the MCP client, not in compose). RAG runs standalone (`:8002`).

---

## 7. Testing summary

| Service | Tests | Notes |
|---|---|---|
| datasets (data plane) | 62 | mapping, XBRL/DART parsers, TTM, screener, scheduler, catalog integrity |
| control-plane | 6 | auth, entitlement resolver, rate-limit, gateway 401/403/200+metering/429 |
| mcp | 4 | tool generation, call success, unentitled 403, import |
| rag | 6 | chunking, hash embedder, ingest→search+provenance, market filter, endpoints |
| **total** | **78** | + live two-/three-service flows verified end-to-end |

---

## 8. Verified live (end-to-end)

- Data plane: real US+KR data (AAPL 2007→ history, Samsung financials, Berkshire 13F, BOK base rate…).
- Gateway: tenant → activate `yahoo` → real AAPL price through control-plane → datasets; `sec_edgar` 403.
- MCP: 28 tools from the catalog; activated tool → real data; unactivated → 403.
- RAG: real `oss-cpu` (fastembed) semantic search with provenance.
- Compose: both containers healthy; real SEC data across the two containers from one shared `.env`.
