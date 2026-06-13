# Roadmap & Task Tracker

> Living checklist for the platform. Companion: [`ARCHITECTURE.md`](./ARCHITECTURE.md).
> Status: ✅ done · ⬜ todo · 🚧 partial.

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
- ✅ Unified `docker compose` (data plane + control plane) + single shared `platform/.env`

---

## Next ⬜

### P4 — Agent Engine  ⬜ (next major)
Build & run agents over a tenant's activated connectors + MCP + RAG.
- ⬜ LLM router (Gemini) — single shared router (mine `services/engine/llm/router.py` for the pattern)
- ⬜ Agent runtime (LangGraph): tools = activated connectors (via gateway/MCP) + RAG `search`
- ⬜ Two builder modes: declarative SDK against the connector contract; **natural-language → agent spec** compiler
- ⬜ Per-tenant sandbox, metering, budgets; guardrails ("not investment advice", **no forecasting**)
- ⬜ Provenance propagated into agent outputs (citations)

### Value-Chain flagship  ⬜ (separate service `platform/value-chain/`)
Rebuilt platform-native; a user-cloneable agent template (see the value-chain DESIGN draft).
- ⬜ VC0 scaffold: theme model, build/read-graph API, `DatasetsClient`; nodes from company facts + prices
- ⬜ VC1 sourced edges: segments + filing text via RAG → supplier→customer edges w/ source + verbatim span
- ⬜ VC2 quantify + reconcile (two-ledger, confidence+interval, conflict-flag, 10%/conservation bounds)
- ⬜ VC3 platform-native (MCP/RAG) + expose as a cloneable Agent-Engine template
- ⬜ VC4 (optional) minimal viz; disclosure-calendar refresh

### Platform hardening
- ⬜ Wire **RAG into the gateway + MCP** as a `search` tool (currently RAG is standalone)
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
