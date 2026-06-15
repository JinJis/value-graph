# Roadmap & Task Tracker — single source of truth

> **One file.** This merges the old `ROADMAP.md` (technical backlog) and `UX_ROADMAP.md` (product
> milestones) into one prioritized, dependency-ordered plan. **Pull your next task from here.**
>
> Companion docs — read the one a task points to before building:
> - **What it should feel like, screen by screen / why it's not a chatbot:** [`UX_SPEC.md`](./UX_SPEC.md)
> - **How the services fit together (current state):** [`ARCHITECTURE.md`](./ARCHITECTURE.md)
> - **Engineering rules + invariants:** [`../CLAUDE.md`](../CLAUDE.md)
>
> **Status:** ✅ done · 🚧 partial · ⬜ todo. **One task per PR;** tag the id in branch/commits/PR
> (e.g. `[PH-2]`, `[U3-ARTIFACT-01]`). Not done until acceptance criteria + the Definition of Done
> (`../CLAUDE.md` §7) pass, with docs/test-totals updated in the same PR.
>
> **Test totals (current): 206 unit** — datasets 78 · control-plane 13 · mcp 9 · rag 17 (+2 oss-cpu
> semantic) · agent-engine 54 · studio-api 31 (+ admin 11) — plus the web build, four docker harnesses
> (`coverage.sh` every catalog tool · `e2e.sh` stub · `e2e_functional.sh` real data+MCP+semantic RAG ·
> `e2e_live.sh` real Gemini), and the **quality eval** `eval/run_eval.py` (14 scenarios incl. multi-turn;
> 59/59 checks + judge 5.00/5). `scripts/test_all.sh` runs everything.

---

## 0. How to read this

**The product** (one line): a *personal research desk* — the user staffs **standing analysts** on their
own **watchlists**, every figure is a **live, sourced artifact**, and the desk **pushes what changed
before being asked**. Three pillars carry the whole plan:

| Pillar | What it means | Where it lands |
|---|---|---|
| **Trust by construction** | no number without a source; gaps drawn, not faked; guardrail label shown | PH-2/3/4, U2, U3 |
| **Pull → Push** | analysts run on a schedule / disclosure event and deliver briefs | U1, U4 |
| **Ecosystem** | publish an analyst, clone someone else's with your data substituted in | U5 |

**Sequencing logic.** The plumbing works, but it's hollow and reads robotic, and it isn't operable. So
the order is:

1. **Phase 1 — Platform Hardening & Quality (PH).** Make the data *real*, the answers *human*, the system
   *operable*. Everything visual is hollow until this is done. **← current top priority.**
2. **Phase 2 — Research-desk UX (U2–U5, U0).** Convert "a chatbot with a data-source picker" into the
   research desk of `UX_SPEC.md`. Each milestone depends on PH trust/data being solid.

Within a phase, follow the tier/dependency order given. The foundation milestones (**U1 watchlists**,
**U-SHELL desk shell**) are already done — Phase 2 builds on them.

---

## 1. What's built ✅

### Data plane (`datasets/`, pkg `app`)
- ✅ US+KR financial API: company facts, prices + snapshot, 3 financial statements (+combined), filings,
  macro (FRED/ECOS), metrics snapshot, news, earnings, insider, 13F (filer-mode).
- ✅ Point-in-time / restatement-aware ingestion store (SQLite/Postgres); screener + line-item search.
- ✅ Bulk / deep-history backfill (SEC `companyfacts.zip` stream → AAPL to 2007; KR via DART).
- ✅ Scheduler (periodic + deep), self-test endpoint, `🚧 Not Implemented (501)` doc tag for unbuilt routes.
- ✅ **Company search/autocomplete** `GET /company/search?q=&market=&limit=` (U1): SEC company_tickers +
  DART corp list, shared `rank_company_matches` (exact→prefix→substring), manifest + catalog + coverage.

### Platform core
- ✅ **Connector manifests + `/catalog`** (keystone): provenance + license per resource; single source the
  REST docs, MCP tools, RAG registration, entitlement, metering, and the agent tool list all derive from.
- ✅ **Control plane / gateway** (`controlplane`): tenancy, scoped keys, activation/entitlements, the
  gateway (auth→entitle→rate-limit→meter/audit), metering, audit log.
- ✅ **MCP** (`mcpserver`): one tool per catalog resource, auto-derived, routed through the gateway with
  the tenant key. **Verified working.**
- ✅ **RAG** (`rag`): provenance-first chunk→retrieve→rerank; pluggable hash / oss-cpu / gcp / gpu / tei
  backends; `memory`/`pgvector` stores; wired into the gateway + MCP as the `rag__search` tool.
- ✅ **Agent engine** (`agentengine`): tool-calling loop over a tenant's activated connectors + RAG via the
  gateway; pluggable planner `stub` (deterministic CI) | `gemini` (function calling); guardrails
  (no advice / no forecasting); provenance citations; `POST /agent/chat` SSE streaming, multi-turn.
- ✅ Unified `docker compose` (all services) + single shared `.env`; full-stack `scripts/e2e.sh`.

### Product layer
- ✅ **F0 · Chat UI:** Next.js + Auth.js (Google + dev-login); studio-api provisions Google user→tenant +
  default activations, holds the tenant key server-side, stores conversations; streaming chat with a
  tools & sources panel; web on `:3000` in the default stack; e2e covers the full chat chain.
- ✅ **F1 · Agent builder:** `AgentSpec` with per-agent `backend` + system prompt; tool filtering by
  connector id or tool name; `agents` CRUD + 4 seeded templates (종합 리서치 / 공시·실적 / 시황·가격 /
  거시경제); `GET /connectors` data-source picker; per-user scoped, templates clone-to-edit; builder modal.
- ✅ **F2 · Prompt library:** `prompts` CRUD + 5 seeded community prompts; `POST /prompts/{id}/import`
  clones a community prompt (idempotent, records `source_id`) — the **clone pattern** U5 generalises;
  library modal (내 프롬프트 / 커뮤니티).

### Research-desk foundation
- ✅ **U1 · Watchlists & @groups** *(Pull→Push foundation — the personalization unit everything binds to)*.
  Search any listed company → ⭐ favorite into a named `@handle` group → `@`-tag it in the composer and
  the analyst builder; the agent resolves the group to its tickers before planning.
  - ✅ **U1-01 · datasets company search** — see Data plane above. +3 tests.
  - ✅ **U1-02 · studio-api watchlist model + CRUD** — `Watchlist {id, user_email, name(@handle)}` +
    `WatchlistItem {id, watchlist_id, market, ticker, name}`; `GET/POST /watchlists`,
    `GET/PATCH/DELETE /watchlists/{id}`, `POST /watchlists/{id}/items`, `DELETE …/items/{item_id}`;
    per-user scoped, unique @handle (409 on dup), add-item idempotent, a company may be in many groups. +4.
  - ✅ **U1-03 · @handle resolution** — `groups.expand_text`/`resolve_messages` expand `@handle` →
    `@handle (handle = 삼성전자 [005930, KR], …)` in user turns **and** an analyst's system prompt before
    it reaches agent-engine; the bare-handle message is what's persisted/shown. Unknown→"알 수 없는 관심
    그룹", empty→"빈 그룹". +2.
  - ✅ **U1-04 · web search/favorite + 관심 rail + @ composer** — `Watchlists` UI (create/rename/delete
    groups, debounced search → ⭐ favorite, remove items) + `@` autocomplete; BFF `/api/watchlists` (+sub-
    routes) + `/api/company/search`; studio-api gateway-proxied `/company/search` (tenant key, entitled). +1.
- 🚧 **U-SHELL · Desk app shell** *(makes the product look like `UX_SPEC` §4 now)*.
  - ✅ **U-SHELL-01 · web shell** — 3-pane grid (slim left rail 데스크·보드·분석가·관심·브리프·갤러리 ·
    center desk · right **Live Context** pane); rail nav with active state + "곧" placeholders for unbuilt
    tabs; 관심 promoted from modal to embedded rail screen; new visual identity applied (matte
    black/gray/white, mono numerics, pixel mascot, trust = the only saturated color). Web build green.
  - ⬜ **U-SHELL-02** — see Phase 2 (thinking state & live tool indicator; pull-anytime).

---

## 2. The plan

### Phase 1 · Platform Hardening & Quality (PH) — 🔴 CURRENT TOP PRIORITY

> Pulled ahead of UX (2026-06-14, after a full audit). Three things undermine the working plumbing:
> **(1) answers read like a machine** (raw tool ids, canned disclaimer, ugly citations); **(2) the data
> stores are empty by default** (scheduler off, backfill manual-only, no RAG ingestion pipeline → screener
> / historical / `rag__search` return nothing for real users); **(3) it isn't operable** (admin is
> raw-HTML + insecure, no ingestion visibility). Order respects dependencies. UX resumes in Phase 2.

#### Tier 0 — make the data real *(everything else is hollow without it)*
- ✅ **PH-1 · Ingestion operability.** `IngestionJob` log + `app/store/jobs.py`
  (start/finish/list + `run_backfill`); `POST /admin/backfill` + `GET /admin/jobs`; admin dashboard shows
  **per-market store breakdown + empty-store warning + recent-jobs table**; `.env.example` documents
  `SCHEDULER_*` + backfill. **Verified live:** AAPL+MSFT 0→5,734 facts (2007→2026), KR DART works,
  screener returns real data. *(datasets + admin)*
  - ✅ **PH-1b · universe presets + live progress + queue guard.** Curated `universes.py` presets
    (`us_mega`/`us_large`/`kr_large`) selectable in admin; `IngestionJob.total`/`done` give **per-ticker
    progress** (admin auto-refreshes while running); `backfill_running` **serializes** runs (busy returned
    synchronously). **Verified live:** `us_mega` 4/15→15/15, 15 cos · 34,506 facts. +7 datasets, +2 admin.
    *(Real distributed queue + migrations = PH-11.)*
- ✅ **PH-2 · RAG ingestion pipeline (news live).** RAG started empty; now a real pipeline indexes content
  per tenant so `rag__search` returns real, cited, semantic hits. Delivered as 2a + 2b:
  - ✅ **PH-2a · per-tenant doc isolation.** `IngestDoc`/`Chunk` gain a `tenant` (control-plane
    `project_id`), namespaced into the chunk id (no cross-tenant PK clobber) and stored in pgvector `meta`
    (excluded from user-facing `provenance()`). The **gateway injects `X-Tenant-Id` from the caller's key**
    when proxying the RAG service (client-supplied values stripped — no spoofing); RAG ingest stamps it,
    search filters **own-tenant OR global (unscoped)** docs so the shared corpus stays visible. *(rag +
    control-plane)* +3 rag, +1 control-plane.
  - ✅ **PH-2b · news ingestion pipeline.** `datasets/app/store/news_ingest.py`: pull Google News per
    ticker → map headlines → IngestDocs (source=publisher, doc_type=news, ticker, as_of, url) → index into
    RAG as a **global corpus** (news is public/identical per tenant → visible to all via PH-2a's
    own-or-global rule, not copied per tenant). `POST /admin/news/ingest` (background, serialized, recorded
    as an `IngestionJob` kind `news`) + admin ops-console form + an optional scheduler tick
    (`SCHEDULER_NEWS`). **Verified live:** AAPL → 8 headlines indexed, `rag/search "Apple news"` returns
    real sourced hits (Trefis/Finviz/Motley Fool, with as_of + url). *(datasets + admin)* +4 datasets.
  - *Filing/other document-text ingestion is consolidated into **PH-RAG** (do it once, when more text
    sources exist — see the linear order below). Persistent `oss-cpu` + `pgvector` defaults = **PH-2d**,
    which lands with **PH-11** (no Postgres in compose until then).*

#### Tier 1 — answer quality *(most visible; mostly independent)*
- ✅ **PH-3 · Answer-quality quick wins.** (a) catalog `name` → friendly `connector_name`/`friendly`
  label per tool; stub summary + Gemini synth use it, raw `opendart__income_statements` no longer leaks;
  (b) `dedup_citations` (+ stream-time de-dup) collapses repeated (source,url); (c) canned "투자 자문…"
  disclaimer dropped from prose (kept as the persistent UI footer label); (d) Gemini final-answer prompt
  rewritten (concise, source-by-institution-name, no tool ids, no appended disclaimer). web renders the
  friendly label + de-duped sources. +2 agent-engine.
- ✅ **PH-13 · LLM-based guardrails.** `GeminiGuardrailer` classifies price-prediction / advice violations
  via Gemini (JSON, temp 0), regex `StubGuardrailer` fallback, `get_guardrailer(backend)` factory — catches
  Korean variants regex missed. *(agent-engine)*
- ✅ **PH-14 · Multi-step planner & tool selection.** GeminiPlanner passes real conversation+tool history
  to GenAI (sequential tool calls), `thought_signature` mapping (avoids 400 on chained calls), public
  `resolve_ticker` (company name/alias → ticker inside the loop), injected date context + per-param
  schema descriptions, `.text` bypass. *(agent-engine)*
- ✅ **PH-15 · LLM-assessed step budget & strict loop guarantees.** A **light Gemini model
  (`AGENT_BUDGET_MODEL`, e.g. flash-lite) assesses the query's complexity → the step budget** — no
  hardcoded keyword rules (falls back to the plain default budget on stub/CI or assess failure). Then the
  budget is strictly honored: the loop **reserves its last step for guaranteed synthesis** (force-finalize),
  a non-empty **fallback answer** replaces the old "Reached the step limit." leak, and an **identical
  consecutive call is detected** → synthesize instead of looping. *(agent-engine)* +5 tests → 54.
- ✅ **PH-4 ( = U2 ) · Perplexity-style inline citations + source-preview cards.** *The signature
  trust feature — folded here from UX.* Depends on PH-3 + citation metadata; sits at the Phase 1↔2 seam.
  Delivered in 4a/4b/4c:
  - ✅ **PH-4a · enriched citation model (agent-engine).** `Citation` gains `index` (1-based [n] anchor),
    `kind` (filing\|news\|metric\|data — named `kind` not `type` to avoid the SSE envelope collision),
    `doc_type`, `as_of`, `freshness`, `snippet`, `ticker`, `page`. RAG citations populate all of it from
    per-hit provenance; datasets citations get a `kind`; `freshness.py` computes fresh/aging/stale from
    `as_of`. Carried through the SSE `citation` event + `done` list + `RunResult` (studio-api persists
    citations as schema-less JSON → backward-compatible). *(agent-engine)* +4 tests → 43.
  - ✅ **PH-4b · web source-preview cards + legend.** `SourceCard.tsx`: type-aware cards (filing
    verbatim-span / metric / news snippet + "맥락 정보 — 전망 아님") keyed by `kind`, with a freshness
    dot; `CiteChip` compact inline `[n]` chips under each message; one reused `TrustLegend`. Chat captures
    the enriched citation fields; right Live Context pane renders full cards, matte palette (freshness =
    the only color). *(web)*
  - ✅ **PH-4c · inline `[n]` anchoring in prose.** Gemini final-answer prompt instructs inline `[n]` in
    source-appearance order; a deterministic floor appends a trailing `[n]` anchor group when the model
    emitted none (covers stub + streaming), matching the citation indices. Web renders `[n]` as superscript
    anchors titled with the cited source. *(agent-engine + web)* +3 agent-engine tests → 46.
  - ✅ **PH-4d · substantive answers — markdown + datasets-source enrichment + de-noise.** Real-world
    answers looked flat because (a) the web rendered assistant **markdown as plain text**, and (b) only
    RAG citations were enriched — **datasets/news sources were bare** generic chips. Fixed: web renders
    markdown (`react-markdown` + GFM tables); `/news` citations now carry the **publisher + headline +
    date** (not "Google News"); financial/metric citations get **`as_of` from the latest report period** +
    freshness; the gemini prompt stops dumping raw URLs in prose; **tool labels de-duped** in the web (one
    row per source, not eight). *(agent-engine + web)* +2 agent-engine tests → 48.
  - ✅ **PH-4e · inline `[n]` ↔ citation-index alignment.** The model numbered `[n]` by its own narrative,
    so a prose `[2]` could point at a different source than chip `[2]`. Fix: thread a `number_sources()`
    block (our authoritative numbering) into the planner's `system_instruction` and instruct gemini to cite
    **only those exact numbers, never reorder**. **Verified live:** NVDA query → prose `[1][2][3]` map
    exactly to Barron's/TipRanks/Yahoo Finance chips. *(agent-engine)* +1 test → 49.

### ▶ Order of remaining work — linear (each item's dependencies precede it)

> Do top-to-bottom. `↳` = the dependency that fixed this position; items with no `↳` are ordered by value.
> New data endpoints **auto-expand REST + MCP tools + RAG registration** (one manifest → all surfaces).
> Detail for each item is in the bullets below this list.
>
> **Finish the data substance**
> 1. **PH-5** — cheap universe endpoints (+ `/filings/items`).  ← **next**
> 2. **PH-MACRO** — cloud-safe macro (DBnomics / Treasury).
> 3. **PH-6** — store-backed: 13F ticker-mode + historical metrics.  ↳ populated store ✅
> 4. **PH-8** — index / ETF holdings (SEC N-PORT).
> 5. **PH-7** — XBRL depth: segments + as-reported.
> 6. **PH-RAG** — unified RAG corpus: ingest **all** document-text sources at once (filing text from PH-5,
>    segment/MD&A from PH-7, transcripts, … + news ✅) → chunk·embed·index.  ↳ PH-5 / PH-7 text  *(was PH-2c)*
> 7. **PH-9** — KPIs via Gemini from filings/earnings text.  ↳ PH-RAG
>
> **Make it deployable**
> 8. **PH-10** — admin → real ops console.
> 9. **PH-11** — productionization: Postgres + Redis + Alembic + job queue + CI + observability  *(the infra gate)*.
> 10. **PH-2d** — `oss-cpu` + `pgvector` as defaults.  ↳ PH-11
> 11. **PH-12** — governance / licensing + BYO-key.
> 12. **PH-DEFER** — paid adapters (Polygon / Tiingo / FMP / KIS).  ↳ PH-12
>
> **Research-desk UX (differentiators)**
> 13. **U-SHELL-02** — thinking & tool-execution indicator  *(pull anytime)*.
> 14. **U3** — inline live artifacts + Board.  ↳ U2 ✅
> 15. **U4** — standing analysts (push): calendar · schedule · briefs · Telegram.  ↳ U1 ✅ + PH-11
> 16. **U5** — gallery clone / substitution + publish.  ↳ U4 + PH-12
> 17. **U0** — onboarding, full flow.  ↳ U5  *(minimal onboarding already shippable on U1)*

#### Item detail

- ⬜ **PH-5 · Cheap universe endpoints.** Implement the trivial 501s: `/filings/tickers`, `/filings/ciks`,
  `/earnings/tickers`, `/company/facts/ciks`, `/prices/snapshot/market`, and `/filings/items` (filing
  text — also feeds PH-2). *(datasets, mostly S)*
- ⬜ **PH-6 · Store-backed endpoints.** #18 13F **ticker-mode** (reverse-CUSIP index) + #21 **historical
  financial-metrics** (ratios across periods). *(datasets; needs PH-1 populated store)*
- ⬜ **PH-7 · XBRL depth.** #20 **segments** + **as-reported** financials (XBRL direct parse, US+KR). *(L)*
- ⬜ **PH-8 · Index/ETF holdings (#19).** US SEC N-PORT; KR KRX/DART later. *(M)*
- ⬜ **PH-RAG · Unified RAG corpus ingestion.** *(was PH-2c — deferred until more text sources exist, then
  done once.)* When the text-bearing endpoints land (filing text via PH-5 `/filings/items`, segment/MD&A
  text via PH-7, earnings-call transcripts, …), ingest them **all** through one pipeline → chunk → embed →
  index per tenant (reusing the PH-2b news pipeline shape). Turns `rag__search` from news-only into the
  full document corpus. *(datasets/rag; M)* — ↳ PH-5 (+ PH-7) for the text.
- ⬜ **PH-9 · KPIs via Gemini (#22)** from earnings text (Gemini extraction + metering). *(↳ PH-RAG text)*
- ⬜ **PH-MACRO · cloud-safe macro provider (FRED alternative).** FRED's `api.stlouisfed.org` serves a
  **JS bot-wall (not JSON) from datacenter IPs** even with a valid key (confirmed: `coverage.sh` shows
  FRED `503 · datacenter IP wall`) → US macro breaks in cloud. Add a `macro_provider_us` selection (mirror
  `prices_provider_*`) with a **keyless, cloud-safe** backend — **DBnomics** (`api.db.nomics.world`,
  mirrors FRED series ids → drop-in for FED/ECB/BOE/BOJ rates) and/or **US Treasury FiscalData** (par
  yields) — and fall back FRED→DBnomics automatically. Keeps series semantics + the manifest; same trust
  envelope. *(datasets; S–M)* — ties to PH-11 (cloud deploy). KR ECOS unaffected.
- ⬜ **PH-DEFER · Paid adapters (#24)** (Polygon/Tiingo/FMP/KIS realtime; KR majorstock 5%) — needs keys;
  tie to BYO-key / governance (PH-12).

- ⬜ **PH-10 · Admin → real ops console.** Harden auth (hash/secret + rate-limit, drop `admin`/`admin`);
  styled dashboard (not raw HTML); job-history + RAG-index-stats + per-market store + per-tenant usage
  views; bulk-backfill form. *(admin)*
- ⬜ **PH-11 · Productionization (#23).** Postgres + Redis (cache / rate-limit / quota / scheduler), **DB
  migrations (Alembic)**, real distributed job queue, CI running all tests, slim images,
  observability/metrics. *(the infra gate — PH-2d, U4 scheduler, and cost quotas all sit on this.)*
- ⬜ **PH-2d · Persistent + real-embedding defaults.** Default `oss-cpu` embedder + `pgvector` store (the
  RAG corpus survives restarts; semantic search is real, not lexical). *(↳ PH-11 brings Postgres.)*
- ⬜ **PH-12 · Governance / licensing enforcement + BYO-key.** Redistribution rules, BYO-key fallback for
  restricted feeds (`license.redistribution=false` → yahoo/news) — also unblocks U5 clone of yahoo/news
  and PH-DEFER paid adapters.

---

### Phase 2 · Research-desk UX — milestone detail *(do-order is the linear list above)*

> Converts "a chatbot with a data-source picker" into the research desk of `UX_SPEC.md`. Foundation
> (U1, U-SHELL-01, and **U2 = PH-4a–e**) is done; the blocks below detail the rest.

#### U2 — Source-preview cards  ✅  *(delivered via PH-4a–e — see Phase 1 above)*
<details><summary>original spec (for reference)</summary>

**Goal:** every inline citation `[n]` opens a **type-aware preview** — filing (verbatim highlighted span),
price/metric (computation + next refresh), news (snippet + "context only") — each with a freshness dot.
- **datasets/rag:** citations carry enough to render the preview — `source`, `url`, `as_of`, `doc_type`,
  and for filings a **page ref + verbatim span** (rag already stores section/accession; extend the
  connector + retrieval payload so the cited span returns).
- **agent-engine:** enrich each citation with `{type, span?, page?, as_of, freshness,
  next_expected_update?}`; freshness from `as_of` vs the disclosure calendar (calendar lands in U4 —
  until then compute from `as_of` only).
- **web:** the three preview-card variants (`UX_SPEC` §5.3), hover (desktop) / tap (mobile), drag-to-pin;
  **one** trust-legend component (freshness dot + confidence-chip border) reused everywhere.

**Acceptance:** in a real answer, hovering a filing citation highlights the exact cited sentence on its
filing page with `as_of` + freshness; a price citation shows connector + computation; a news citation
shows the snippet labelled "맥락 정보 — 전망 아님".
</details>

#### U3 — Inline live artifacts + Board  ⬜
**Goal:** figures render as **interactive cards backed by connectors** (refreshable), gaps are drawn, and
cards can be **pinned to a Board** that auto-refreshes.
- **agent-engine:** emit a typed **artifact spec** alongside prose (`{kind: timeseries|compare|table|
  mini-graph, series[], provenance[]}`); guardrail renders **no** artifact for refused asks.
- **web:** artifact renderer (charts; R3F only where a graph view is warranted), `↻새로고침` re-calls the
  connector, `⇄표로 보기` toggle, dashed gap segments; **Board** screen = grid of pinned artifacts, each
  re-fetching on open with its own freshness line. **Never render the graph with DOM nodes** (WebGL/R3F +
  instanced meshes).
- **studio-api:** `PinnedArtifact { id, user_email, spec(JSON), created_at }` CRUD for the Board.

**Acceptance:** ask for a multi-name margin comparison → an interactive card with per-series sources +
freshness; pin it; reopen the Board next day → refreshed values with a new `as_of`.

#### U4 — Standing analysts (push): schedule · disclosure calendar · briefs · channels  ⬜  *(subsumes F3)*
**Goal:** an analyst **runs headless on a schedule or a disclosure event** and delivers a **brief** to the
in-app inbox and Telegram. *This is the daily reason to return.*
- **datasets:** a **Disclosure Calendar** endpoint — per-company next expected filing/earnings date
  (`GET /calendar?ticker=&market=`), derived from filing cadence + known earnings dates (KR DART schedule,
  US 10-Q/10-K cadence). Powers `next_expected_update` and the freshness `stale` state from U2.
- **studio-api:** extend `Agent` → `kind: chat|standing`, `target_watchlist_id`, `schedule(cron)`,
  `triggers(JSON)`, `channels(JSON)`, `output_format`; add `AnalystRun` + `Brief { run_id, title, body,
  citations, read }`; runner `POST /analysts/{id}/run` (also "미리보기 실행").
- **pipeline/scheduler:** the datasets scheduler gains an **analyst tick** calling the studio-api runner
  for due analysts; disclosure-calendar events enqueue runs (D-3). Meter headless runs.
- **agent-engine:** a headless run mode producing the brief artifact (reuses the tool loop; output =
  brief). Guardrails unchanged.
- **integrations (F3):** Telegram channel — connect bot → deliver brief card.
- **web:** standing-analyst builder additions (targets/schedule/triggers/channels, NL↔form, 미리보기) +
  the `🔔 브리프` inbox (read/unread) + deep-link from a brief line into the Desk pre-loaded.

**Acceptance:** create a standing analyst on `@반도체바스켓` at 08:00 + disclosure D-3 → the scheduler
runs it headless → a sourced brief appears in the inbox and (if connected) Telegram, with a header
stating why it fired; tapping a line opens the Desk in that context.

#### U5 — Gallery: clone/substitution + publish-back  ⬜
**Goal:** browse published analysts, **clone** one (binding wizard re-maps its slots to *my* watchlist /
activations / channels → a personal instance with provenance), and **publish** my own (re-abstracted,
private data stripped).
- **studio-api:** define the **AnalystTemplate slots** schema (`UX_SPEC` §5.7); `GET /gallery`,
  `POST /gallery/{id}/clone` (idempotent, records `source_id`+`source_version` — mirrors prompt-import F2),
  `POST /analysts/{id}/publish` (re-abstract: strip `target_watchlist_id` → `targets` slot, derive
  `data_sources` from used connectors, compute `cost_estimate`, attach badges).
- **control-plane:** clone checks the user's **activations** per required connector; restricted feeds
  trigger **BYO-key or skip** (completes governance — PH-12).
- **web:** Gallery grid (badges `sourced·no-forecast·auditable`, author, ★, clone count, cost) + the
  4-step clone wizard + a publish flow.

**Acceptance:** clone a gallery analyst targeting the author's basket → the wizard binds it to *my*
`@반도체바스켓`, flags `news` as restricted (BYO-key or skip), runs a preview, and the saved instance
records `source_id`; publishing my analyst produces a template with **no** private watchlist.

#### U0 — Onboarding (cold-start)  ⬜  *(incremental: min with U1, full after U5)*
**Goal:** a new user reaches **first sourced value in < 90s** — pick market → search+favorite (or interest
chips) → hire a starter analyst → land on a **non-empty desk**.
- **studio-api:** onboarding state on `User` (completed?); interest-chip → representative-tickers map;
  seed the first watchlist + (full version) bind a starter Gallery template.
- **web:** onboarding flow (market → chips/search → ⭐ → hire → seeded "내 관심 한눈에" artifact on the
  Desk). Minimal (with U1): market + search/favorite + seeded desk. Full (post-U5): hire-a-starter via the
  clone wizard.

**Acceptance:** a brand-new Google login is never shown an empty desk; within the flow they create a
watchlist and (full) hire an analyst whose first brief is scheduled.

#### U-SHELL-02 — Thinking state & live tool-execution indicator  ⬜  *( ≡ F0-thinking; pull-anytime)*
Render the mascot's thinking animation/state in the chat message stream and a dynamic progress indicator
of active tool calls (e.g. "삼성전자 공시를 분석하는 중…", "Yahoo Finance 시세를 가져오는 중…") derived
from the SSE `tool`/`tool_result` events. Independent of the other U milestones — pair it with PH answer-
quality work for perceived-quality lift. *(web)*

---

## 3. Cross-cutting (always-on)
- ⬜ **Trust envelope intact** through RAG + agent + artifacts + briefs (U2/U3 depend on it): every
  datum/chunk/artifact/brief carries source + as_of + freshness (+ confidence/interval where derivable).
- ⬜ **Per-tenant cost quotas/budgets** (data + LLM + agent loops) — meter headless analyst runs (U4) and
  clone previews (U5). Lives in control-plane; needs Redis (PH-11).
- ⬜ **"Not investment advice" + no forecasting** enforced at the agent boundary and **shown** in the UI
  (PH-13 + the persistent footer label). It's the trust brand, not fine print.
- ⬜ **One Gemini router, one tenancy model** — no forks of the router / auth / schema across services.

---

## 4. Data-plane 501 backlog (detail)
Tracked above under PH-5–PH-9 / PH-DEFER; listed here as the raw endpoint inventory.
- ⬜ #18 13F **ticker-mode** + investor/ticker discovery (reverse-CUSIP index — feasible with the store) → PH-6
- ⬜ #19 Index funds / ETF holdings (US SEC N-PORT, KR KRX/DART) → PH-8
- ⬜ #20 Segments + as-reported financials (XBRL direct parse) → PH-7
- ⬜ #21 Historical financial-metrics (derive ratios across periods from the store) → PH-6
- ⬜ #22 KPIs via Gemini extraction from earnings releases → PH-9
- ⬜ Document-text → RAG corpus (filing text, segments/MD&A, transcripts) → PH-RAG (consolidated; was PH-2c)
- ⬜ #24 Paid adapters (Polygon/Tiingo/FMP, KIS realtime) + KR institutional (majorstock 5%) → PH-DEFER
- ⬜ Cheap universe 501s (`/filings/tickers|ciks`, `/earnings/tickers`, `/company/facts/ciks`,
  `/prices/snapshot/market`, `/filings/items`) → PH-5

> The do-order is the single linear list in §2 ("▶ Order of remaining work"). Keep this file's status
> markers + test totals current in the same PR as each task.
