# Roadmap & Task Tracker — single source of truth

> **One file.** This merges the old `ROADMAP.md` (technical backlog) and `UX_ROADMAP.md` (product
> milestones) into one prioritized, dependency-ordered plan. **Pull your next task from here.**
>
> Companion docs — read the one a task points to before building:
> - **What it should feel like, screen by screen / why it's not a chatbot:** [`UX_SPEC.md`](./UX_SPEC.md)
> - **How the services fit together (current state):** [`ARCHITECTURE.md`](./ARCHITECTURE.md)
> - **Web visual language / component templates (the wireframe, implemented):** [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) ← derived from the wireframes (open `.dc.html` with `wireframes/support.js`; intent in `wireframes/chat-*.md`): [`wireframes/app-map.dc.html`](./wireframes/app-map.dc.html) (app map), [`wireframes/screens.dc.html`](./wireframes/screens.dc.html) (**7 full-size screens + source viewer**), `wireframes/community.dc.html` (community/insights — U6)
> - **Engineering rules + invariants:** [`../CLAUDE.md`](../CLAUDE.md)
> - **Exploratory ideas (not commitments; promote only with approval):** [`IDEA.md`](./IDEA.md)
>
> **Status:** ✅ done · 🚧 partial · ⬜ todo. **One task per PR;** tag the id in branch/commits/PR
> (e.g. `[PH-2]`, `[U3-ARTIFACT-01]`). Not done until acceptance criteria + the Definition of Done
> (`../CLAUDE.md` §7) pass, with docs/test-totals updated in the same PR.
>
> **Test totals (current): 261 unit** — datasets 117 · control-plane 13 · mcp 9 · rag 17 (+2 oss-cpu
> semantic) · agent-engine 69 · studio-api 34 (+ admin 12, renderer 5) — plus the web build, four docker harnesses
> (`coverage.sh` every catalog tool · `e2e.sh` stub · `e2e_functional.sh` real data+MCP+semantic RAG ·
> `e2e_live.sh` real Gemini), and the **quality eval** `eval/run_eval.py` (22 scenarios incl. multi-turn,
> graded by a **deep-model rubric** — 5 dimensions, see `eval/RUBRIC.md`; run before every push).
> `scripts/test_all.sh` runs everything.

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
  macro (FRED/ECOS), metrics snapshot, news, earnings, insider, 13F (filer-mode), ETF/fund holdings (US N-PORT).
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
  - ✅ **U-SHELL-DESIGN · wireframe re-skin** — whole web UI re-skinned to the user's wireframe
    (`docs/wireframes/app-map.dc.html`): **light grayscale** system (white cards on `#E9E9EB`, near-black ink
    actions), Space Grotesk + Space Mono fonts, trust signals the only saturated color, visible
    guardrail label (Live feed · builder · **refused turns** via the `done` SSE `refused` flag) +
    composer trust-meta. Tokens + templates documented in `docs/DESIGN_SYSTEM.md`; components consume
    tokens (no hardcoded hex). Confidence tiers kept spec-only (no `confidence` field yet → not faked).
    Web build green; stack boots; light tokens verified in the compiled bundle.
  - ✅ **U-SHELL-DS · unified design system + Desk 1:1** — added the primitive library
    `web/components/ui.tsx` (`Button`/`Chip`/`Card`/`FreshnessDot`/`TrustLegend`/`GuardrailLabel`/
    `Mascot`/`Modal`) as the single source for recurring patterns; refactored Chat/AgentBuilder/
    PromptLibrary/Watchlists/SourceCard/ArtifactCard to compose them (one `FreshnessDot`, one
    `Modal`). Rebuilt the **Desk** to the wireframe composition: horizontal rail (brand wordmark ·
    nav rows · account footer with `tenant ✓`), analyst header (mascot + status dot + switcher),
    composer placeholder + @group chips + source meta, source-preview card C layout. API documented
    in `docs/DESIGN_SYSTEM.md` §4. Web build green; DS classes verified in the bundle. (D–I screens
    next, on confirmation.)
  - ✅ **U-SHELL-LIVECTX · Live Context source previews + viewer** — reworked the Live Context
    panel from a title list into **native source previews** with the cited passage highlighted
    (`SourceCard` → `.srcprev`: filing = mini PDF page + page badge, web = browser chrome + URL bar +
    highlight, data = extracted card), panel header "인용 원문 N" + guardrail note; clicking a preview
    opens the **full source viewer** (`SourceViewer.tsx`, wireframe Screen 08) with the passage
    highlighted + a "이 원문을 인용한 곳" panel (freshness/as_of/source · 원문 열기 ↗ · 인용 복사).
    Maps onto real `Citation` data (kind/url/page/snippet/freshness); skeleton lines stand in for
    un-redistributed surrounding text. New design files saved to `docs/wireframes/screens.dc.html` +
    `wireframes/community.dc.html`. Web build green. *(Detailed pages for 분석가/브리프/갤러리 are
    backend-blocked — analysts list, brief inbox = push/PH-11, gallery = community/Phase-2 — tracked
    under U4/U5; community = lowest priority per the user.)*
  - ✅ **U-SHELL-PROV · Live Context = evidence, with canonical links + real data** — reworked the whole
    provenance path so Live Context shows only the sources that *actually produced the answer*, each with
    a canonical link and the specific figures used (not every consulted source, not a bare "지표 계산값"):
    - **datasets:** `metrics_history` now surfaces `accession_number` + a canonical `filing_url` per period;
      new `app/store/provenance.py` `filing_link()` (SEC **index page** from cik+accn — not the bare
      directory listing; DART rcpNo viewer). SEC `_filing_url` upgraded to the index page. +1 test (86).
    - **agent-engine:** `_citations` extracts the canonical filing link (`filing_url`/`source_url`/accession,
      never an incidental directory URL) + builds a real-data **snippet + extracted table** from the actual
      figures; RAG chunks get a canonical link built from their accession when they lack a url; filings
      listings emit one evidence card per document. `mark_evidence()` flags `used` = cited `[n]` OR backs an
      artifact → only evidence is anchored/shown; `done` SSE carries `used`. Artifacts carry `url`. +3 (64).
    - **web:** Live Context filters to `used` citations (consulted-but-unused stay in the answer's 도구·출처);
      `SourceCard`/`SourceViewer` render the extracted **table** (cited row highlighted) + canonical link.
    - **eval:** the store-backed metrics + filings scenarios already exercise the enriched provenance
      path (judge 5/5); corrected the News scenario's brittle `expect_cite` (news cites the *publisher*,
      not the "Google News" label). Full eval green (85/85 deterministic, judge 3.94/5). e2e + web build green.
  - 🚧 **PH-PROV2 · Deterministic visual evidence** *(the trust engine — show the cited number
    highlighted in the real filing; SEC iXBRL first)*. The LLM produces the number (API = source of
    truth); a **deterministic** engine maps it to its exact location in the source document — never
    the LLM. Plan: `~/.claude/plans/sequential-sleeping-dongarra.md`. PRs PR2–PR5 + infra fold-in below.
    - ✅ **PH-PROV2a · vertical slice (US iXBRL, end-to-end).** `datasets/app/providers/us/ixbrl.py`
      deterministically matches a companyfacts fact `(concept, period, value)` to its `<ix:nonFraction>`
      element (normalizes scale/sign/parentheses; disambiguates prior-year columns + note duplicates;
      `miss`/`unavailable` never fabricated); `FactLocation` pointer table + `locations_ingest`
      precompute + `POST /admin/precompute-locations`. New **`renderer`** microservice (Playwright,
      isolated Chromium) highlights the element and screenshots its row, cache-first on a volume.
      datasets `GET /evidence` (gateway-proxied utility route → renderer cache-first → PNG, else 204);
      `Citation.evidence_image_url` composed in `agent.py` (lazy — just the link, no render in the
      stream); studio-api + web BFF stream the PNG with the tenant key; `SourceViewer` shows the
      highlighted screenshot, falling back to the text card on 204/error. datasets 86→94, agent-engine
      64→66, studio-api 33→34, **renderer 5** (new); web build green.
    - ✅ **PH-PROV2b · income-statement concepts + disambiguation hardening.** Matcher now prefers the
      **consolidated** (non-dimensional) context over per-segment duplicates (companyfacts = consolidated
      totals); `lookup_location` + `/evidence` accept a **candidate concept list** (revenue maps to
      different us-gaap tags across filers — try each in order); agent `_FIELD_CONCEPTS` reverse map wires
      the common **income_statements** shape (normalized fields → candidate concepts) to evidence, not just
      `as_reported`. Verified live on AAPL (consolidated revenue line FY2025 → 200 PNG). datasets 94→96,
      agent-engine 66→67. **Admin UX:** the Backfill forms now carry a **📷 evidence** checkbox so an
      operator indexes fundamentals + visual-evidence pointers in one click; `/admin/precompute-locations`
      resolves a universe preset to its US tickers and skips non-US (evidence is SEC iXBRL only).
      datasets 96→97, admin 11→12.
    - ✅ **PH-PROV2c · balance + cashflow + quarterly + scheduler/deep-backfill wiring.** Agent now
      attaches evidence (image + extracted table) for **balance_sheets** (instant XBRL contexts →
      total_assets/liabilities/equity) and **cash_flow_statements** (duration → operating/investing/
      financing CF), via a generalized `_STATEMENT_HEADLINES` reverse map. Precompute now indexes
      **both annual (10-K) AND quarterly (10-Q)** — "latest revenue" surfaces the most recent quarter, so
      quarter-only figures need pointers too (the annual-only gap that hid the screenshot for a Q query).
      Scheduler/deep-backfill wiring: `ingest_ticker` best-effort precomputes US pointers behind
      `PRECOMPUTE_LOCATIONS` (the scheduler's `ingest_universe` goes through it → manual + scheduled both
      covered). datasets 97→99, agent-engine 67→69.
    - ✅ **PH-PROV2d · KR DART document evidence.** DART exposes no PDF/iXBRL — the OpenDART
      `document.xml` API returns a ZIP of the disclosure document as HTML-ish markup. New
      deterministic matcher `datasets/app/providers/kr/dart_document.py` (KR analog of `ixbrl.py`):
      **label-anchors the statement row** by its Korean account name (매출액/영업이익/자산총계…) and
      **exact-matches the value cell** at the unit scales DART tables use (원/천원/백만원/억원, △/()
      negatives) — pure text match, no LLM, gaps → `miss`/`unavailable` never faked. `FactLocation`
      gains KR rows (market="KR"); `locations_ingest._precompute_kr` downloads each filing's document
      once and indexes its headline figures; `/admin/precompute-locations` + the ingest hook now accept
      KR. **Renderer reused** (no PyMuPDF, no new dep): the `/evidence` KR path re-finds the cell at
      render time and injects a unique `#id` (DART markup parsed by lxml vs. Chromium diverge —
      `<tbody>`/tag-case — so a positional XPath isn't reused) for the existing `/render/sec` HTML path;
      cache key stays unique per fact. agent-engine `_evidence_url` composes the KR link (market=KR,
      field-name concept). datasets 99→105, agent-engine 69→70. *(Real-DART verification needs an
      `OPENDART_API_KEY` on the deployment stack; the matcher is unit-tested against a DART-shaped fixture
      and every gap degrades to the text source card.)*
      - **Bugfix (PH-PROV2 web, US+KR):** the chat SSE→state capture (`web/components/Chat.tsx`)
        reconstructed each citation field-by-field and **dropped `evidence_image_url` + `table`**, so the
        highlighted-filing screenshot (and the extracted-data table) could **never** render in the Live
        Context / source card even when the backend served them — the actual reason evidence wasn't
        showing end-to-end. Now carried through. (The agent emits them via `c.model_dump()`; studio-api +
        gateway proxy `/evidence` correctly; renderer is wired in compose.)
      - **Bugfix (PH-PROV2d, KR persist):** KR statement models expose `filing_url` as a pydantic
        `AnyUrl` (not a str); writing it straight into `FactLocation.primary_doc_url` made SQLite reject
        the bind (`type 'AnyUrl' is not supported`) so the KR `_upsert` failed and **no KR pointer ever
        persisted** → `/evidence` always 204 (US matched because its path uses plain-str dict values).
        Coerced to `str`; verified live (Samsung revenue → matched, scale=6). +1 regression test → 106.
    - ⬜ **PH-PROV2e** — RAG-chunk evidence (highlight a text span in MD&A/transcripts). ↳ PH-RAG.
      *(folded into PH-PROV3 below — same PDF + on-demand-locate mechanism.)*
    - ⬜ **infra fold-in** — `FactLocation`→Postgres, image cache + first-render dedup→Redis. ↳ PH-11.
  - 🚧 **PH-PROV3 · Evidence at scale — PDF document store + on-demand locate** *(supersedes the
    concept-precompute model; approved 2026-06-20)*. The pointer-precompute (PH-PROV2a–d) only covered a
    **fixed set of headline concepts** per filing — it can't answer the *many* arbitrary questions users
    ask, is slow to precompute, and never covered narrative text. Invert it: **cache the whole filing as a
    PDF once** (universal coverage, one render/filing) and **locate + highlight on demand** whatever the
    answer actually cited (figures by value-match, passages by span-match), with the renderer out of the
    query hot-path. Decisions: PyMuPDF lives in `datasets` (no renderer hop at query time); migration is
    additive (build the PDF path beside the old one, switch `/evidence`, then retire the concept-pointer
    path); ingestion is **watchlist-scoped**. US iXBRL HTML / KR DART markup → PDF at ingest (no forced
    PDF where none exists — US has no official PDF, so we normalize). Other sources keep their natural
    evidence (news/web = snippet+link; prices/macro = data card).
    **Source decision (verified 2026-06-21): KR = DART's official PDF** (`pdf/download/pdf.do`, keyless,
    Chromium-free, the full 540-page report) **· US = render iXBRL HTML→PDF ourselves** (no SEC PDF
    exists; sec-api.io offers a paid render API but it's the same operation outsourced — self-host the
    one-shot Chromium render instead). So Chromium is gone from KR entirely and from the query hot-path
    for both; it remains only for the one-shot US ingest render.
    - ✅ **PH-PROV3a · PDF document store + ingest normalization.** New `EvidenceDoc` model (cached
      PDF per filing, keyed `market`+`accession`, with the canonical `원문 열기` link). Renderer
      `POST /pdf/from-html` (Chromium `page.pdf()`, one-shot at ingest — query-time stays browser-free).
      `app/store/evidence_docs.py`: `ensure_doc` (fetch source → renderer → write PDF to the data volume
      → index; idempotent), `build_evidence_docs_for_ticker` / `run_build_evidence_docs` (watchlist-scoped,
      recorded as an `IngestionJob` kind `evidence_docs`); `POST /admin/evidence-docs` trigger. KR
      `filing_url` AnyUrl coerced to str (same hazard as PH-PROV2d). datasets 106→108, renderer 5→8.
    - ✅ **PH-PROV3b · PyMuPDF on-demand highlight + KR official PDF.** KR ingest now pulls DART's
      **official PDF** (`dart_document.fetch_dart_pdf`: resolve the main `dcmNo` from the viewer →
      `pdf/download/pdf.do`; document.xml→renderer kept as fallback) — **no Chromium for KR**. New
      `app/store/evidence_render.py` (PyMuPDF): finds the cited value in the cached PDF at the unit scales
      statements use (ones/천/백만/억), anchored on its account label (KR_LABELS / US gaap→label map),
      highlights the cell, rasterizes the page band → PNG (cache-first). `/evidence` serves the PDF path
      first (browser-free), falling back to the legacy FactLocation+renderer screenshot; new
      `/evidence/doc` streams the real PDF for `원문 열기`. `pymupdf` added to datasets. datasets 108→111.
    - ⬜ **PH-PROV3c · generalize + agent wiring + retire concept-precompute.** RAG/news passage evidence,
      prices/macro data-card evidence, agent citations on the new path; consolidate the filing-accession
      resolution and remove the now-dead `FactLocation` concept-pointer precompute.
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
> 1. ✅ **PH-5** — cheap universe-enumeration endpoints.  *(filing-text `/filings/items` → PH-RAG)*
> 2. ✅ **PH-MACRO** — cloud-safe macro (keyless DBnomics/BIS fallback for FRED).
> 3. ✅ **PH-6a** — historical financial-metrics (store-backed ratios) → MCP tool.  · **PH-6b** (13F
>    ticker-mode / reverse-CUSIP) deferred — needs a 13F-holdings index, not the facts store.
> 4. ✅ **PH-8 (US)** — ETF/fund holdings via SEC N-PORT → MCP tool `sec_edgar__index_funds`.  · KR
>    (KIS-ETF) deferred to the KIS connector.  ← next: **PH-9** (KPIs ↳ PH-RAG text via PH-PROV3e).
> 5. 🚧 **PH-7a** — XBRL as-reported (US) → MCP tool `sec_edgar__as_reported`.  · **PH-7b** (segments +
>    statement-specific as-reported + KR DART XBRL) deferred (dimensional/heavier parse).
> 6. **PH-RAG** — unified RAG corpus: ingest **all** document-text sources at once (filing text from PH-5,
>    segment/MD&A from PH-7, transcripts, … + news ✅) → chunk·embed·index.  ↳ PH-5 / PH-7 text  *(was PH-2c)*
> 7. **PH-9** — KPIs via Gemini from filings/earnings text.  ↳ PH-RAG
> 8. **PH-SOURCES** *(later)* — alt-data corpus: brokerage/market reports, investor blogs, Threads/Reddit,
>    finance books → into PH-RAG.  ↳ PH-RAG + **per-source legal/licensing clearance**
>
> **KR killer features (KIS — 한국투자증권; platform-held key, subscription-metered — NOT BYO-key)**
> All ↳ **platform KIS app key/secret (being issued)** + gateway metering. Approved 2026-06-15.
> - **KIS-0** — KIS client/auth foundation (app key/secret → token, KR-market REST client, rate-limit-aware).
> - **KIS-FLOW** — investor-flow connector (개인/외국인/기관 순매수) → MCP tool. *KR-unique killer signal.*
> - **KIS-RANK** — KR rankings/screeners (거래량·등락·시총·52주·공매도) → MCP tool(s).
> - **KIS-ETF** — KR ETF holdings + NAV → MCP tool (this is the **KR half of PH-8**).
> - **KIS-PRICES** — `prices_provider_kr=kis` (real-time / intraday KR prices + indices) — upgrades the
>   existing provider slot beyond delayed Yahoo.
>
> **Make it deployable**
> 8. **PH-10** — admin → real ops console.
> 9. **PH-11** — productionization: Postgres + Redis + Alembic + job queue + CI + observability  *(the infra gate)*.
> 10. **PH-2d** — `oss-cpu` + `pgvector` as defaults.  ↳ PH-11
> 11. **PH-12** — governance / licensing + subscription metering (BYO-key only as a license fallback).
> 12. **PH-DEFER** — paid adapters (Polygon / Tiingo / FMP / KIS).  ↳ PH-12
>
> **Research-desk UX (differentiators)** — visual spec: `wireframes/screens.dc.html` (7 full-size screens) +
> `wireframes/community.dc.html`; **every screen composes the `ui.tsx` primitives — see `DESIGN_SYSTEM.md` for
> tokens/components so the language stays unified.** ✅ Desk + Live Context (light DS, native source previews +
> expand viewer) already shipped — U-SHELL-DESIGN/DS/LIVECTX above.
> 13. **U-SHELL-02** — thinking & tool-execution indicator  *(pull anytime)*.
> 13b. ✅ **U-BUILDER-01** — expandable data-source → **tool transparency** in the builder.
> 13c. **U-SHELL-POLISH** — detail-pass the already-real screens to `wireframes/screens.dc.html`: Board head (핀 수 ·
>      마지막 새로고침 · 전체 새로고침); 관심 = @group sidebar + stock table + favorite→group popover; **분석가**
>      list page (현재 "곧" → render `/api/agents`). *Frontend-only, unblocked — do alongside its backend milestone.*
> 14. ✅ **U3** — inline live artifacts + Board.  *(01 spec · 02 web card · 03a pin+Board · 03b ↻refresh — all done)*
> 15. **U4** — standing analysts (push): calendar · schedule · briefs · Telegram.  ↳ U1 ✅ + PH-11  *(브리프 inbox = detail Screen 5)*
> 16. **U5** — gallery clone / substitution + publish.  ↳ U4 + PH-12  *(gallery + 4-step wizard = detail Screen 6)*
> 17. **U0** — onboarding, full flow.  ↳ U5  *(detail Screen 7; minimal already shippable on U1)*
> 18. **U6** — Community / Insights *(lowest priority, per user)*: blog-style insight authoring with embedded LIVE
>      artifacts, upvote/scrap/follow, author reputation/badges, data hub.  ↳ U5 + PH-RAG + PH-12.

#### Item detail

- ✅ **PH-5 · Cheap universe-enumeration endpoints.** Implemented the trivial 501s: `/filings/tickers`,
  `/filings/ciks`, `/company/facts/ciks` (SEC ticker index / DART corp map via new `list_ciks()` provider
  method), `/earnings/tickers` (company universe), `/prices/snapshot/market` (snapshots the store's tracked
  tickers, bounded by `limit`; per-ticker failures skipped, never faked). Removed from `scaffold.py`'s
  501 list. Following the existing `/…/tickers` convention these are **plain utility routes, not catalog
  resources** → they don't add MCP tools (MCP-tool growth comes from data-bearing PH-6/7/8/PH-RAG).
  *(datasets)* +4 tests → 82. Filing **text** (`/filings/items`) deferred to **PH-RAG**.
- ✅ **PH-6a · Historical financial-metrics (#21).** `/financial-metrics` (was 501) now derives ratios
  across periods from the store (`store/metrics_history.py`): margins, ROE/ROA, debt-to-equity/assets,
  current ratio, interest coverage, EPS + YoY revenue/earnings/operating-income growth — only where inputs
  exist (gaps stay null, never faked). **Added as a catalog resource on `datasets_store` → a new MCP tool
  `datasets_store__metrics_history` (US+KR)**; coverage.sh "all 32"; eval scenario added. *(datasets)*
  +2 tests → 84.
- ⬜ **PH-6b · 13F ticker-mode (#18).** "which filers hold this security" — needs a **reverse-CUSIP /
  13F-holdings index** (the facts store doesn't hold 13F holdings), so it's a heavier ingestion job, not a
  store query. Deferred. *(datasets; M–L)*
- 🚧 **PH-7 · XBRL depth (#20).**
  - ✅ **PH-7a · as-reported (US).** `/financials/as-reported` (was 501) returns every us-gaap XBRL concept
    **exactly as filed**, per period (latest-filed value per concept; gaps absent, never faked), from SEC
    company-facts. **New MCP tool `sec_edgar__as_reported`** (catalog resource; coverage "all 33"; eval
    scenario added). *(datasets)* +1 test → 85.
  - ⬜ **PH-7b · segments + statement-specific as-reported + KR.** Business/geographic **segments** are
    dimensional XBRL (not in company-facts → needs the filing's R-files/frames); the 3 statement-specific
    `…/as-reported` splits; and **KR DART XBRL** as-reported. Heavier parse — deferred. *(datasets; L)*
- 🚧 **PH-8 · Index/ETF holdings (#19).** **US** ✅ — `/index-funds?ticker=` returns an ETF's
  constituents from its latest **SEC N-PORT** filing (`SecEdgarFundProvider` + `_parse_nport`:
  `<invstOrSec>` → name/cusip/isin/shares/market_value/weight, sorted by value; fund header with
  net-assets + as-of). New catalog resource on `sec_edgar` → MCP tool `sec_edgar__index_funds`;
  `/index-funds/tickers` convenience list; reverse direction (holding→funds) stays 501 (needs a
  holdings index). Verified live (SPY → 503 holdings: NVDA 7.6% / AAPL 6.7% / MSFT 4.9%). +2 tests,
  eval +1, coverage "all 34". **KR** = `KIS-ETF` (component stocks + NAV via the KIS connector) —
  deferred to KIS-0. *(datasets)*
- ⬜ **PH-RAG · Unified RAG corpus ingestion.** *(was PH-2c — deferred until more text sources exist, then
  done once.)* When the text-bearing endpoints land (filing text via PH-5 `/filings/items`, segment/MD&A
  text via PH-7, earnings-call transcripts, …), ingest them **all** through one pipeline → chunk → embed →
  index per tenant (reusing the PH-2b news pipeline shape). Turns `rag__search` from news-only into the
  full document corpus. *(datasets/rag; M)* — ↳ PH-5 (+ PH-7) for the text.
- ⬜ **PH-9 · KPIs via Gemini (#22)** from earnings text (Gemini extraction + metering). *(↳ PH-RAG text)*
- ✅ **PH-MACRO · cloud-safe macro provider (FRED alternative).** FRED's `api.stlouisfred.org` serves a
  **JS bot-wall (not JSON) from datacenter IPs** even with a valid key → US macro breaks in cloud. Added a
  `macro_provider_us` selection (mirrors `prices_provider_*`): `auto` (default) | `fred` | `dbnomics`.
  New **keyless, cloud-safe `DBnomicsProvider`** (`app/providers/us/dbnomics.py`) serves the BIS
  *Central bank policy rates* dataset (`BIS/WS_CBPOL`, daily) for the same `bank` enum (FED→US, ECB→XM,
  BOE→GB, BOJ→JP) — no key, no datacenter gate (FRED is **not** mirrored on DBnomics; BIS is the unified
  cloud-safe source). `AutoMacroProvider` (`macro_auto.py`) tries FRED only when `FRED_API_KEY` is set and
  **falls back to DBnomics on the bot-wall / any upstream failure**; with no key it goes straight to
  DBnomics → US macro works out of the box, keyless, in the cloud. Manifest preserved (the `fred`
  connector is now `requires_key=False`, name/desc/provenance updated to reflect the BIS/DBnomics default —
  no new MCP tools); gaps never faked (`NA` dropped). `.env.example` + datasets README + coverage label
  updated. *(datasets)* +4 tests → 103. KR ECOS unaffected. *(US Treasury FiscalData par-yields = a future
  add — a different resource shape, out of scope for this drop-in.)*
- ⬜ **PH-DEFER · Paid adapters (#24)** (Polygon/Tiingo/FMP; KR majorstock 5%) — needs keys; platform-held
  + subscription-metered (KIS realtime is now its own `KIS-PRICES`, below).

#### KIS — Korea Investment & Securities (KR killer data) *(approved 2026-06-15)*
> **Platform-held key model:** the KIS app key/secret live **server-side** (the user is issuing the KIS
> account) — we provide the data and **charge by subscription**, NOT BYO-key (see memory
> *monetization-subscription*). All KIS-* ↳ that platform key + gateway metering. Trade execution /
> backtester / strategy-builder and **analyst opinions/targets** are **excluded** (out of scope / clash
> with the no-forecast guardrail). `config` already has `kis_app_key`/`kis_app_secret` + a
> `prices_provider_kr=kis` slot.
- ⬜ **KIS-0 · client/auth foundation.** App key/secret → token (24h, cached), KR-market REST client,
  rate-limit-aware (prod vs paper domains). The base every other KIS resource builds on. *(datasets; S–M)*
- ⬜ **KIS-FLOW · investor-flow.** 개인/외국인/기관 net buy/sell (daily + intraday) → catalog resource →
  **MCP tool**. KR-unique signal nobody else exposes. *(datasets; ↳ KIS-0)*
- ⬜ **KIS-RANK · KR rankings/screeners.** 거래량·등락률·시가총액·52주 고저·공매도 순위 → MCP tool(s).
  *(datasets; ↳ KIS-0)*
- ⬜ **KIS-ETF · KR ETF holdings + NAV.** Component stocks + NAV-vs-market → MCP tool. **= the KR half of
  PH-8.** *(datasets; ↳ KIS-0)*
- ⬜ **KIS-PRICES · `prices_provider_kr=kis`.** Real-time / intraday KR prices + index data — upgrades the
  existing provider slot beyond delayed Yahoo. *(datasets; ↳ KIS-0; real-time licensing per governance)*

#### Future — data-source expansion (unstructured / alternative) *(approved to add 2026-06-15; later)*
- ⬜ **PH-SOURCES · Alt-data corpus expansion.** Massively widen what `rag__search` covers beyond
  filings/news: **brokerage & market-analysis reports, notable-investor blogs, Threads/Reddit chatter
  (찌라시), investment/economy/finance books**. All unstructured text → flows through the **PH-RAG**
  pipeline (chunk·embed·index, per-tenant, full provenance + freshness). **Hard gate: legal/licensing
  review per source** (copyright, site ToS/robots, redistribution — books & social especially) before any
  ingestion; store extracted text + source link, minimal quoting (CLAUDE.md compliance). *(rag/pipeline +
  legal; L)* — ↳ PH-RAG + per-source legal clearance.

- ⬜ **PH-10 · Admin → real ops console.** Harden auth (hash/secret + rate-limit, drop `admin`/`admin`);
  styled dashboard (not raw HTML); job-history + RAG-index-stats + per-market store + per-tenant usage
  views; bulk-backfill form. *(admin)*
- ⬜ **PH-11 · Productionization (#23).** Postgres + Redis (cache / rate-limit / quota / scheduler), **DB
  migrations (Alembic)**, real distributed job queue, CI running all tests, slim images,
  observability/metrics. *(the infra gate — PH-2d, U4 scheduler, and cost quotas all sit on this.)*
- ⬜ **PH-2d · Persistent + real-embedding defaults.** Default `oss-cpu` embedder + `pgvector` store (the
  RAG corpus survives restarts; semantic search is real, not lexical). *(↳ PH-11 brings Postgres.)*
- ⬜ **PH-12 · Governance / licensing + subscription metering.** The model is **platform provides all data
  (server-side keys) + subscription billing**, NOT BYO-key (memory *monetization-subscription*). So this is
  primarily **per-source redistribution/licensing rules + subscription tiers/quotas** (metering already
  exists; quotas need PH-11 Redis). **BYO-key stays only as a fallback** for feeds whose license forbids
  platform redistribution. Also gates U5 clone of restricted feeds + per-source clearance for PH-SOURCES.

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

#### U3 — Inline live artifacts + Board  ✅
**Goal:** figures render as **interactive cards backed by connectors** (refreshable), gaps are drawn, and
cards can be **pinned to a Board** that auto-refreshes.
- ✅ **U3-01 · artifact spec (agent-engine).** `Artifact{kind,title,series[{label,unit,points[{x,y}]}],
  source,as_of,freshness,ticker,has_gap,tool}`. `_artifacts(tool,result)` shapes chartable tool results
  (prices→종가 timeseries; metrics_history→margin multi-series; income_statements→매출·순이익) — pure
  data-shaping like citations, not reasoning. Emitted as the SSE `artifact` event + `done.artifacts` +
  `RunResult.artifacts`; refusals emit none. studio-api relays the events transparently. +5 tests → 59.
- ✅ **U3-02 · web artifact card.** `ArtifactCard.tsx` renders the spec as an interactive card —
  dependency-free **SVG multi-series line chart** (matte palette, neutral + sparse accent), `⇄표로 보기`
  toggle, dashed line when `has_gap`, source + freshness dot + as_of, value formatting (T/B/M, % for
  ratios). Chat captures the `artifact` SSE event and renders cards under the assistant bubble. Web build
  green. **eval:** the harness now captures `artifact` events + an `expect_artifact` check; +1 scenario
  ("price chart → timeseries") → 20 scenarios. *(web + eval)*
- ✅ **U3-03a · Board (pin + persist + display).** studio-api `PinnedArtifact{id,user_email,title,spec(JSON)}`
  + `/board` CRUD (per-user); the artifact spec carries `args` so a pin can later re-fetch. Web: **📌 핀**
  button on each chat artifact card → `/api/board`; the **보드** rail tab renders the pinned cards in a grid
  with ✕ remove. *(studio-api + web)* +1 studio test → 32; web build green.
- ✅ **U3-03b · Board refresh.** agent-engine `POST /agent/artifact/refresh` re-runs a pin's `tool`+`args`
  through the gateway and re-shapes a fresh artifact (new `as_of`); studio-api `POST /board/{id}/refresh`
  calls it with the tenant key + updates the stored spec; web `↻새로고침` on each Board card refetches in
  place. *(agent-engine + studio-api + web)* +2 agent-engine, +1 studio test → 61 / 33; web build green.

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
  *Detailed UX:* `wireframes/screens.dc.html` **Screen 3** (분석가 list + builder) and **Screen 5** (브리프 inbox
  + full reading view: numbered changes, `[n]` cites, "why it fired" header). Compose `ui.tsx` primitives
  (Card/Chip/GuardrailLabel/FreshnessDot) — see `DESIGN_SYSTEM.md`. **Frontend-now (unblocked):** the **분석가
  list page** (replace the rail "곧" placeholder by rendering `/api/agents` — chat agents + create/edit/clone)
  ships without the scheduler; the inbox + residency badges wait on the push backend above.

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
  4-step clone wizard + a publish flow. *Detailed UX:* `wireframes/screens.dc.html` **Screen 6** (template
  grid + 4-step wizard: 대상 → 소스 → 트리거·채널 → 미리보기; restricted feed → BYO-key/skip → honest degrade).
  Compose `ui.tsx` primitives; reuse the prompt-import clone pattern. See `DESIGN_SYSTEM.md`.

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
  clone wizard. *Detailed UX:* `wireframes/screens.dc.html` **Screen 7** (4 steps: 시장 → 관심 → 고용 → 비어있지
  않은 데스크). Compose `ui.tsx` primitives; see `DESIGN_SYSTEM.md`. *The market→favorite→seeded-desk steps are
  frontend-now on U1; hire-a-starter waits on U5.*

**Acceptance:** a brand-new Google login is never shown an empty desk; within the flow they create a
watchlist and (full) hire an analyst whose first brief is scheduled.

#### U-SHELL-02 — Thinking state & live tool-execution indicator  ⬜  *( ≡ F0-thinking; pull-anytime)*
Render the mascot's thinking animation/state in the chat message stream and a dynamic progress indicator
of active tool calls (e.g. "삼성전자 공시를 분석하는 중…", "Yahoo Finance 시세를 가져오는 중…") derived
from the SSE `tool`/`tool_result` events. Independent of the other U milestones — pair it with PH answer-
quality work for perceived-quality lift. *(web)*

#### U-BUILDER-01 — Expandable data-source → tool transparency  ✅
`studio-api /connectors` now includes each connector's `tools` (name + description, from the catalog
`resources`); `web/AgentBuilder.tsx` renders each data-source as an expandable row (▸ 툴 N) revealing the
tools inside with a plain-language "what it does" — selection stays connector-level, the expansion is for
transparency (showing *exactly* what an analyst can touch = trust-by-construction). Now e.g. expanding
`datasets_store` shows `metrics_history` "기간별 재무비율 추이". *(studio-api + web)* +0 (extended the
existing `/connectors` test); web build green. See `UX_SPEC.md` §5.5. Per-tool *selection* is a later option.

#### U6 — Community / Insights  ⬜  *(lowest priority, per user — gated on U5 + PH-RAG + PH-12)*
**Goal:** turn the desk into an **ecosystem** — users author blog-style **investment insights** with embedded
**LIVE artifacts** (fresh at read-time, not screenshots), share them, earn upvotes/scraps/followers, and
build reputation. Consumption feeds back into the reader's own assets. Spec: `wireframes/community.dc.html` +
`wireframes/community.dc.html`; design principle from the wireframe — **data signals stay trust-color
(green/amber/red), people/social signals are indigo** (`--accent`); two signal systems kept separate. Every
screen composes `ui.tsx` primitives (`DESIGN_SYSTEM.md`) and **reuses the already-built `SourceCard` native
previews + `SourceViewer`** for footnotes/RAG chunks. Capability-review origin (data·MCP·RAG·Agent → feature
mining) is the wireframe's screen 00.
- **Feed** (`커뮤니티 피드`) — 인기/팔로잉/신규 tabs; post cards embed LIVE artifacts (read-time fresh + "내
  보드로" clone); right-rail **명예의 전당** leaderboard (incl. my rank).
- **Composer** (`인사이트 작성기`) — block editor; drag **my Board artifacts** in to embed; RAG citations become
  auto-footnotes; **pre-publish gate** (sources present · no-forecast); "이 글의 논리를 분석가로 변환". *(Relates
  to the parked **Insight Canvas** idea in `IDEA.md`.)*
- **Reader** (`인사이트 읽기`) — upvote dock, **scrap** (pick collection), discussion thread, artifact "내 보드로
  복제"; footnotes render as **native source previews + 펼치기 → `SourceViewer`** (same trust pattern as Live Context).
- **Author profile** (`작가 프로필 · 명예`) — reputation · followers · scraps-received · published analysts +
  badges (Always-Sourced, …) — the "become known" surface.
- **Scrapbook** (`스크랩북 · 컬렉션`) — saved insights + LIVE artifacts in folders, highlights/notes, curate-on-publish.
- **Data Hub** (`데이터 허브`) — 자료실 (RAG: evidence-chunk citations + native preview + trace), MCP connector
  status (price/filing connected · news BYO-key · custom server), private PDFs never leave the tenant.
- **backend:** posts/collections/upvotes/follows/scraps in studio-api (mirror the prompt-import clone pattern
  for portability); leaderboard/reputation aggregation; moderation/report flow; artifact-embed = a Board-spec
  reference re-resolved at read-time; needs PH-RAG (auto-footnotes) + PH-12 (publish/governance) + moderation.

**Acceptance:** publish an insight embedding a Board artifact and a RAG-cited footnote → it passes the
sources/no-forecast gate → another user reads it (artifacts fresh at read-time), scraps it to a collection,
clones an embedded artifact to their Board, and follows the author; the author's reputation reflects it.

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
- 🚧 #19 Index funds / ETF holdings → PH-8: **US ✅ (SEC N-PORT)**; KR (KIS-ETF) deferred
- ⬜ #20 Segments + as-reported financials (XBRL direct parse) → PH-7
- ⬜ #21 Historical financial-metrics (derive ratios across periods from the store) → PH-6
- ⬜ #22 KPIs via Gemini extraction from earnings releases → PH-9
- ⬜ Document-text → RAG corpus (filing text, segments/MD&A, transcripts) → PH-RAG (consolidated; was PH-2c)
- ⬜ #24 Paid adapters (Polygon/Tiingo/FMP, KIS realtime) + KR institutional (majorstock 5%) → PH-DEFER
- ⬜ Cheap universe 501s (`/filings/tickers|ciks`, `/earnings/tickers`, `/company/facts/ciks`,
  `/prices/snapshot/market`, `/filings/items`) → PH-5

> The do-order is the single linear list in §2 ("▶ Order of remaining work"). Keep this file's status
> markers + test totals current in the same PR as each task.
