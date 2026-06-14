# Roadmap & Task Tracker

> Living checklist for the platform. Companion: [`ARCHITECTURE.md`](./ARCHITECTURE.md).
> Status: ✅ done · ⬜ todo · 🚧 partial.
>
> **Test totals (current): 170 unit** — datasets 67 · control-plane 12 · mcp 9 · rag 14 (+2 oss-cpu
> semantic) · agent-engine 35 · studio-api 31 — plus the web build, three docker e2e harnesses
> (`coverage.sh` every catalog tool · `e2e.sh` stub · `e2e_functional.sh` real data+MCP+semantic RAG ·
> `e2e_live.sh` real Gemini), the
> **quality eval** `eval/run_eval.py` (14 scenarios incl. multi-turn; 59/59 checks + judge 5.00/5), and
> `scripts/test_all.sh` to run everything. (Per-milestone counts below are historical.)

---

## 🔴 Platform Hardening & Quality (PH) — CURRENT TOP PRIORITY

> Pulled ahead of the UX milestones (U2+) on 2026-06-14 after a full audit. The product *plumbing*
> works, but three things undermine it: **(1) answers read like a machine** (raw tool ids, canned
> disclaimer, ugly citations), **(2) the data stores are empty by default** (scheduler OFF, backfill is
> manual-only, RAG has no ingestion pipeline → screener / historical / `rag__search` return nothing for
> real users), and **(3) it isn't operable** (admin is raw-HTML + insecure, no ingestion visibility).
> MCP is verified-working; not a priority. Order below respects dependencies. UX (U2+) resumes after.

**Tier 0 — make the data real (everything else is hollow without it)**
- ⬜ **PH-1 · Ingestion operability.** Scheduler is OFF by default + backfill is CLI-only → `FinancialFact`
  store is empty → `/financials/search/*`, historical metrics, 13F-ticker all return nothing. Add an
  `/admin/backfill` trigger + an `ingestion_jobs` log table (ticker·market·status·rows·started·error);
  surface store stats per market + job history in the admin dashboard; ship a sensible default
  `SCHEDULER_*` config + docs. *(datasets + admin)* — **unblocks PH-5/PH-6 and the screener.**
- ⬜ **PH-2 · RAG ingestion pipeline + real defaults.** RAG starts empty (no pipeline) and defaults to the
  `hash` toy embedder + ephemeral `memory` store. Build a pipeline (news now via Google News; filings
  after PH-5's `/filings/items`) → chunk → embed → index per tenant; default `oss-cpu` + `pgvector`
  (persistent); add per-tenant doc isolation. *(rag + pipeline)* — partially depends on PH-5 for filing text.

**Tier 1 — answer quality (most visible; mostly independent)**
- ✅ **PH-3 · Answer-quality quick wins.** (a) catalog `name` → friendly `connector_name`/`friendly`
  label on each tool; stub summary + Gemini synth prompt use it, raw `opendart__income_statements` no
  longer leaks into answers; (b) `dedup_citations` (+ stream-time de-dup) collapses repeated (source,url);
  (c) canned "투자 자문…" disclaimer dropped from answer prose (kept as the persistent UI footer label);
  (d) Gemini final-answer prompt rewritten (concise, source-by-institution-name, no tool ids, no
  appended disclaimer). web renders the friendly tool label + de-duped sources. +2 agent-engine tests → 35.
- ⬜ **PH-4 (= U2) · Perplexity-style inline citations + source-preview cards.** Enrich the `Citation`
  model (`as_of`/`doc_type`/`freshness`/`index`), anchor inline `[n]` markers to spans, type-aware
  preview cards (filing verbatim-span / metric computation / news snippet). **This is U2, pulled in
  here.** Depends on PH-3 + citation metadata.

**Tier 2 — more tools (depth; several depend on a populated store)**
- ⬜ **PH-5 · Cheap universe endpoints.** Implement the trivial 501s: `/filings/tickers`, `/filings/ciks`,
  `/earnings/tickers`, `/company/facts/ciks`, `/prices/snapshot/market`, and `/filings/items` (filing
  text — also feeds PH-2). *(datasets, mostly S)*
- ⬜ **PH-6 · Store-backed endpoints.** #18 13F **ticker-mode** (reverse-CUSIP index) + #21 **historical
  financial-metrics** (ratios across periods). *(datasets; depends on PH-1 populated store)*
- ⬜ **PH-7 · XBRL depth.** #20 **segments** + **as-reported** financials (XBRL direct parse, US+KR). *(L)*
- ⬜ **PH-8 · #19 Index/ETF holdings** (US SEC N-PORT; KR KRX/DART later). *(M)*
- ⬜ **PH-9 · #22 KPIs via Gemini** from earnings text (needs text ingestion + Gemini + metering). *(depends PH-2)*
- ⬜ **PH-MACRO · cloud-safe macro provider (FRED alternative).** FRED's `api.stlouisfed.org` serves a
  **JS bot-wall (not JSON) from datacenter IPs** even with a valid key (confirmed: `coverage.sh` shows
  FRED `503 · datacenter IP wall`) → US macro breaks in cloud. Add a `macro_provider_us` selection (mirror
  the `prices_provider_*` pattern) with a **keyless, cloud-safe** backend — **DBnomics** (`api.db.nomics.world`,
  mirrors FRED series ids → drop-in for FED/ECB/BOE/BOJ rates) and/or **US Treasury FiscalData** (par
  yields) — and fall back FRED→DBnomics automatically. Keeps series semantics + the connector manifest;
  same trust envelope. *(datasets; S–M)* — ties to PH-11 (cloud deploy). KR ECOS is unaffected.
- ⬜ **PH-DEFER · #24 paid adapters** (Polygon/Tiingo/FMP/KIS) — needs keys; tie to BYO-key/governance (PH-12).

**Tier 3 — production hardening**
- ⬜ **PH-10 · Admin → real ops console.** Harden auth (hash/secret + rate-limit, drop `admin`/`admin`);
  styled dashboard (not raw HTML); job-history + RAG-index-stats + per-market store + per-tenant usage
  views; bulk-backfill form. *(admin)*
- ⬜ **PH-11 · Productionization (#23).** Postgres + Redis (cache/rate-limit/quota), CI running all tests,
  slim images, observability/metrics.
- ⬜ **PH-12 · Governance/licensing enforcement + BYO-key.** Redistribution rules, BYO-key fallback for
  restricted feeds (also unblocks U5 clone of yahoo/news + PH-DEFER paid adapters).

**Then resume UX:** U2 is folded into PH-4; U3 (artifacts+board) · U4 (standing analysts/push) · U5
(gallery clone) · U0 (onboarding) follow per `UX_ROADMAP.md`.

---

## Done ✅

### Data plane (`platform/datasets/`)
- ✅ US+KR financial API: company facts, prices+snapshot, 3 financial
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
- ✅ In the unified compose default stack (`docker compose up` serves web on :3000); e2e covers the full chat chain

### Product layer — agent builder  ✅ (F1)
Users create/configure agents and pick from provided templates; a chat runs through the chosen agent.
- ✅ `agent-engine`: `AgentSpec` gains a per-agent `backend` (`stub|gemini`) + system-prompt passthrough;
  tool filtering accepts connector ids (`yahoo` → all its tools) as well as full tool names
- ✅ `studio-api`: `agents` CRUD + 4 seeded provided templates (종합 리서치 / 공시·실적 / 시황·가격 / 거시경제);
  `GET /connectors` (data-source picker); `/chat/stream` takes `agent_id` → builds the `AgentSpec`;
  the conversation records which agent drove it; agents are per-user scoped, templates are read-only (clone to edit)
- ✅ `web`: agent picker (templates + my agents) + builder modal (name/model/system prompt/data-source
  checkboxes); BFF routes `/api/agents`, `/api/agents/[id]`, `/api/connectors`; chat sends `agent_id`
- ✅ e2e: a custom agent restricted to `sec_edgar` answers a price question **without** reaching `yahoo`

### Product layer — prompt library  ✅ (F2)
A personal prompt collection + a seeded community catalog users import from.
- ✅ `studio-api`: `prompts` CRUD (`/prompts`, `/prompts/{id}`) + 5 seeded community prompts
  (`/prompts/community`, read-only); `POST /prompts/{id}/import` clones a community prompt into the user's
  library (idempotent, records `source_id`). Per-user scoped; community rows are `user_email = NULL`.
- ✅ `web`: prompt library modal (내 프롬프트 / 커뮤니티 tabs) — create/edit/delete personal prompts,
  import community ones, **사용** drops the prompt body into the composer. BFF routes `/api/prompts`
  (+`[id]`, +`[id]/import`, +`community`).
- ✅ e2e: list community prompts → import one → assert an editable copy (with `source_id`) lands in the library

### Product layer — next phase  ⬜ (F3)
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
