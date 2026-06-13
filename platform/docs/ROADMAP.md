# Roadmap & Task Tracker

> Living checklist for the platform. Companion: [`ARCHITECTURE.md`](./ARCHITECTURE.md).
> Status: ✅ done · ⬜ todo · 🚧 partial.
>
> **Test totals (current): 126 unit** — datasets 63 · control-plane 12 · mcp 9 · rag 14 ·
> agent-engine 17 · studio-api 11 — plus the web build and the full-stack `scripts/e2e.sh`.
> (The per-milestone counts below are historical, as of when each phase landed.)

---

## Done ✅

### Data plane (`platform/datasets/`)
- ✅ US+KR financial API (financialdatasets.ai-compatible): company facts, prices+snapshot, 3 financial
  statements (+combined), filings, macro (FRED/ECOS), metrics snapshot, news, earnings, insider, 13F (filer)
- ✅ Point-in-time ingestion store (SQLite/Postgres), screener + line-items search
- ✅ Bulk / deep-history backfill (companyfacts.zip stream; AAPL → 2007; KR via DART)
- ✅ Scheduler (periodic + deep), self-test endpoint, `🚧 Not Implemented (501)` doc tag
- ✅ 62 tests

### Platform
- ✅ **P0** Connector manifests + `/catalog` (keystone) — provenance + license per resource
- ✅ **P1** Control plane: tenancy, scoped keys, activation/entitlements, gateway, metering, audit, rate-limit (6 tests)
- ✅ **P2** MCP server: tools auto-derived from catalog, routed through gateway w/ tenant key (4 tests)
- ✅ **P3** RAG: provenance-first retrieval; pluggable CPU-OSS / GCP / GPU backends via `.env` (6 tests)
- ✅ Unified `docker compose` (data plane + control plane + **rag**) + single shared `platform/.env`
- ✅ RAG integrated into gateway + MCP (`rag__search` tool); full-stack `scripts/e2e.sh`
- ✅ 86 unit tests + e2e

---

## Next ⬜

### P4 — Agent Engine  ✅ (`platform/agent-engine/`)
Runs agents over a tenant's activated connectors + RAG via the gateway.
- ✅ Tool-calling loop: tools resolved from the gateway catalog; calls routed through the gateway (entitled + metered)
- ✅ Pluggable planner: `stub` (deterministic, dev/CI) | `gemini` (function calling)
- ✅ Two builder modes: declarative `AgentSpec`; NL `/agent/compile`
- ✅ Guardrails ("not investment advice", **no forecasting**); provenance citations in outputs
- ⬜ Follow-ups: full LangGraph graph; per-tenant budgets; Gemini planner live-tested with a key

### Product layer — chat UI  ✅ (F0)
A Claude-style web app where users freely ask about holdings/news/markets/economy and the agent answers
with sources. **Value-chain flagship was dropped.**
- ✅ `agent-engine` streaming multi-turn chat (`POST /agent/chat` SSE)
- ✅ `studio-api`: Google user→tenant provisioning + default activations (via control-plane admin),
  conversations, chat BFF that holds the tenant key server-side
- ✅ `web` (Next.js + Auth.js Google, dev-login fallback): streaming chat with a tools & sources panel
- ✅ In unified compose (web under `ui` profile); e2e covers the full chat chain

### Product layer — next phases  ⬜ (F1–F3)
- ⬜ **F1 Agent builder:** create/configure agents (model `stub|gemini`, selected data sources =
  activation subset, system prompt); pick from provided agents. (studio-api `agents` table is ready.)
- ⬜ **F2 Prompts + community:** personal prompt library + seeded community catalog with import. (`prompts`)
- ⬜ **F3 Messengers:** Telegram/Slack connect → inbound webhook runs an agent → reply. (`integrations`)

### Platform hardening
- ✅ Wire **RAG into the gateway + MCP** as a `search` tool — `rag` connector (`service: rag`) in the
  catalog; gateway routes `/rag/search`; MCP auto-exposes `rag__search`. Full-stack `scripts/e2e.sh`.
- ⬜ **Governance/licensing enforcement**: redistribution rules, BYO-key fallback for restricted feeds, legal review
- ⬜ RAG ingestion pipeline: pull filing text (`/filings/items`) + news → chunk → embed → index (per tenant)
- ⬜ Productionization (#23): Postgres + Redis (cache, rate-limit, quota), CI running all tests, slim images, observability
- ⬜ Tenant self-service UI / API beyond admin endpoints

---

## Data-plane backlog (remaining `501`s) ⬜
- ⬜ #18 13F **ticker-mode** + investor/ticker discovery (reverse CUSIP index — now feasible with the store)
- ⬜ #19 Index funds / ETF holdings (US SEC N-PORT, KR KRX/DART)
- ⬜ #20 Segments + as-reported financials (XBRL direct parse)
- ⬜ #21 Historical financial-metrics (derive ratios across periods from the store)
- ⬜ #22 KPIs via Gemini extraction from earnings releases
- ⬜ #24 Paid adapters (Polygon/Tiingo/FMP, KIS realtime) + KR institutional (majorstock 5%)

---

## Cross-cutting (always-on) ⬜
- ⬜ Keep provenance/trust envelope intact through RAG + agent outputs
- ⬜ Per-tenant cost quotas/budgets (data + LLM + agent loops)
- ⬜ Enforce "not investment advice" + no prediction/forecasting at the agent boundary
- ⬜ One Gemini router, one tenancy model — no forks

---

## Suggested sequence
1. **RAG → gateway/MCP integration** (small; makes RAG a first-class tenant tool)
2. **P4 Agent Engine** (the big unlock for "users build agents")
3. **Value-Chain flagship** on top of P4
4. **Governance/licensing + productionization** before any external multi-tenant launch
