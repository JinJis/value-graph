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
> **Status:** ✅ done · 🚧 partial · ⬜ todo · 🗑 dropped. **One task per PR;** tag the id in branch/commits/PR
> (e.g. `[PH-2]`, `[U3-ARTIFACT-01]`). Not done until acceptance criteria + the Definition of Done
> (`../CLAUDE.md` §7) pass, with docs/test-totals updated in the same PR.
>
> **🗑 Scope decision (2026-06-23, per user):** CE **Wave 2** (CE-11..14 — FMP / KIS / premium news,
> built when keys land) **will proceed**. **All other unstarted backlog is DROPPED** (not building):
> PH-10/11/12 productionization (Postgres/Redis/governance/metering), PH-2d, PH-6b 13F ticker-mode,
> PH-7b XBRL segments, PH-SOURCES, PH-DEFER paid adapters, and the U4/U5/U6/U0 product epics
> (standing analysts · gallery · community · onboarding). The shipped platform (PH + CE Wave 1) + Wave 2
> is the scope.
>
> **Test totals (current): 347 unit** — datasets 144 · control-plane 13 · mcp 9 · rag 18 (+2 oss-cpu
> semantic) · agent-engine 121 · studio-api 42 (+ admin 18, renderer 4) — plus the web build, four docker harnesses
> (`coverage.sh` every catalog tool · `e2e.sh` stub · `e2e_functional.sh` real data+MCP+semantic RAG ·
> `e2e_live.sh` real Gemini), and the **quality eval** `eval/run_eval.py` (32 scenarios incl. multi-turn,
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

1. **Phase 0 — Content & Data Expansion (CE).** ✅ foundation is real/human/operable, so now **keep adding
   investment/finance/economics content** (the 8 feature categories) on top — every feature cited, with
   live provenance/evidence. **← current top priority.** See `DATA_EXPANSION.md`.
2. **Phase 1 — Platform Hardening & Quality (PH).** ✅ shipped — data made real, answers human, system
   operable (multi-agent reasoning, charts, provenance, pipelines, ops console).
3. **Phase 2 — Research-desk UX (U2–U5, U0).** Convert "a chatbot with a data-source picker" into the
   research desk of `UX_SPEC.md`. (Much delivered; standing analysts/push/community remain.)

Within a phase, follow the tier/dependency order given. The foundation milestones (**U1 watchlists**,
**U-SHELL desk shell**) are already done — Phase 2 builds on them.

---

## 1. What's built ✅ — shipped summary

> The platform foundation is **done and operable**. Condensed below; the detailed per-task archive
> follows (kept for reference). **Active work is now §2 → the CE phase (top of the plan).**

**Shipped phases (all ✅):**
- **Data plane** — US+KR fundamentals/filings/prices/macro/news/earnings/insider/13F/ETF-holdings;
  point-in-time store + screener; company search; **PH-PIPE** pipeline registry + multi-pipeline
  scheduler + `PriceBar`/`CorporateAction` stores + dynamic universes (S&P500/KOSPI/KOSDAQ via SEC/
  pykrx→OpenDART fallback); WAL concurrency fix.
- **Platform core** — connector manifest/`/catalog` (single source) · control-plane gateway (tenancy/
  keys/entitlement/meter) · MCP · RAG (provenance-first) · agent-engine · unified docker compose.
- **Provenance/evidence (PH-PROV)** — every structured figure → highlighted filing screenshot +
  "원문 열기" real PDF; filing/news text → RAG with passage evidence; data-card evidence for non-docs.
- **Answer quality (PH-3/4/13/14/15/THINK)** — inline `[n]` citations + source-preview cards; LLM
  guardrail folded into the intake (no regex); multi-step planner; **multi-agent orchestration**
  (intake → clarify-with-options → conceptual route → A2A decompose → **parallel** gather → verify +
  per-source confidence → **rich responder that mixes evidence + analysis**); **real token streaming**;
  deep follow-up suggestions; model tiering (flash-lite intake · flash routing · **pro synthesis**).
- **Charts (PH-VIZ 1–6)** — TradingView Lightweight engine; sourced event markers; Gemini annotations;
  technical overlays; user drawing tools + pinnable; PNG export; full-history load + OHLCV/financials
  tables with 더보기; KR names + abbreviated big numbers.
- **Product/UX** — chat UI (Claude-like centered column, our gray+indigo palette) with **session
  history/resume**, inline sources, pinning, watchlists/@groups, prompt library (27 prompts), the
  fully-loaded **Gemini default agent**; admin ops console (catalog/pipelines/data/users/DB + operator-
  controlled refresh); KPI desk; macro DBnomics.

---

### (archive) Data plane (`datasets/`, pkg `app`)
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
    - ✅ **PH-PROV2e** — **universal web evidence**: news/web citations now carry a W3C **text-fragment
      deep link** (`url#:~:text=…`) so "원문 ↗" opens the live article scrolled to + highlighting the
      cited phrase (browser-native, best-effort, no screenshot). Filings keep the PDF screenshot path.
      `text_fragment_url` in citations.py; applied to Google News + news RAG passages. +1 agent test.
    - ⬜ **infra fold-in** — `FactLocation`→Postgres, image cache + first-render dedup→Redis. ↳ PH-11.
  - ✅ **PH-PROV3 · Evidence at scale — PDF document store + on-demand locate** *(supersedes the
    concept-precompute model; approved 2026-06-20; a–f all shipped)*. The pointer-precompute (PH-PROV2a–d) only covered a
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
    - ✅ **PH-PROV3c · auto-build evidence docs + "원문 열기" = the real PDF.** The ingest hook
      (`PRECOMPUTE_LOCATIONS`) and the admin "📷 evidence" checkbox now **cache filings as PDFs**
      (`build_evidence_docs`, US + KR) instead of the old concept pointers, so evidence works for a
      backfilled/watchlist ticker with no separate step; `/admin/evidence-docs` gained preset support.
      "원문 열기" now opens the **actual cached PDF**: datasets `/evidence/doc` → studio-api proxy →
      web `/api/evidence/doc`; `SourceViewer` links to it once the highlight image has loaded (so the
      PDF is known to exist), else the official source page. studio-api 34→35.
    > **▶ Generalization goal (approved 2026-06-21): evidence for EVERY figure and EVERY passage in
    > every SEC/DART filing — not just headline revenue.** The unlock is that the **cached PDF is one
    > artifact with two uses**: (1) the **full-text corpus** the agent searches (RAG), and (2) the
    > **evidence source** it highlights. So "search any info" and "show its evidence" become the same
    > pipeline over the same PDF. Today only ~4 headline fields are wired and only structured figures —
    > d/e/f below close that. SEC/DART first; prices/macro/news keep their natural (non-PDF) evidence.
    - ✅ **PH-PROV3d · every STRUCTURED figure gets evidence (SEC/DART) + retire legacy.**
      - ✅ **answer-aware anchoring + widened coverage.** The evidence image now anchors on the figure
        the **answer actually cites** (`evidence_url_for_answer`: scan every statement field, newest
        period, for a value that appears in the answer text → net income / R&D / assets / cash-flow get
        their own highlight, not always revenue) — falls back to the headline when nothing matches. Field
        + label maps widened from 4 headlines to **every income/balance/cash-flow line** (agent
        `_FIELD_CONCEPTS`/`_STATEMENT_HEADLINES`, datasets `US_GAAP_LABELS`, `KR_LABELS`). chat.py
        re-anchors post-answer and the **web now honors `done.citations`** (the authoritative, re-anchored
        set). +1 agent test → 71.
      - ✅ **logging.** datasets had no logging config → INFO never reached `docker logs` and best-effort
        `except` blocks swallowed failures. Added `app/logging_config.py` (LOG_LEVEL, default INFO) + INFO
        logs across the evidence pipeline (doc build stored/skipped, DART pdf fetch, PyMuPDF hit/miss,
        `/evidence` 204 reason).
      - ✅ **retired the legacy path.** Deleted `FactLocation` (model), `store/locations_ingest.py`,
        `providers/us/ixbrl.py` (+ its tests), `/admin/precompute-locations`, and the renderer's
        `/render/sec` screenshot path; `/evidence` is now PDF-only (no FactLocation fallback, no
        `/evidence/meta`); `_primary_doc_map` moved into `evidence_docs`. renderer 8→4, datasets 115→102
        (dead tests removed). The cached PDF + PyMuPDF is the single evidence path.
    - ✅ **PH-PROV3e · every PASSAGE searchable + evidenced — full filing text → RAG (the big one).**
      *This is what makes "search all info in all datasources" real; folds in PH-RAG + PH-PROV2e.*
      One PDF = corpus + evidence. *(supersedes standalone PH-RAG for the SEC/DART text corpus; news
      stays its own global corpus.)*
      - ✅ **filing text → RAG (slice 1).** `store/filing_ingest.py`: each cached filing PDF → per-page
        text (PyMuPDF) → RAG IngestDocs with provenance `{accession, section=p.N, ticker, market,
        source, doc_type=filing}` (reuses the PH-2b `/rag/ingest` helper; RAG already carries
        `accession`+`section` through to hits — no RAG change). `POST /admin/filings/ingest` (preset +
        watchlist-scoped, ensures the PDFs first), IngestionJob kind `filing_text`. So `rag__search`
        can now return real filing passages. datasets 102→104.
      - ✅ **text-span evidence (slice 2).** `/evidence` `text=` mode → `evidence_render.highlight_text_png`
        PyMuPDF `search_for`s a distinctive leading slice of the cited passage (tries 10→6→4 words as
        long phrases wrap) → highlights + rasterizes the band. studio-api `/evidence` now forwards `text`
        (concept/report_period made optional); web already forwards all params.
      - ✅ **agent wiring (slice 3).** `_rag_citations` attaches `rag_evidence_url(market, accession, text)`
        for filing hits (news/web hits have no accession → none), so a narrative answer's RAG source
        highlights its passage in the cached PDF. agent-engine 71→72; datasets 104→105.
    - ✅ **PH-PROV3f · non-document datasources → data-card evidence.** prices/macro/metrics/financials
      render the **exact values used + source + as_of + freshness** as a data card (no PDF, by design) —
      that IS their evidence. Added a clean macro **interest-rate shaper** (`기관·금리·기준일`); prices /
      metrics / statements already had shapers; other row shapes use the generic extractor. news/web →
      publisher snippet + link. Trust envelope now closed across every source. agent-engine 72→73.
  - ⬜ **U-SHELL-02** — see Phase 2 (thinking state & live tool indicator; pull-anytime).

---

## 2. The plan

### Phase 0 · Content & Data Expansion (CE) — 🔴 CURRENT TOP PRIORITY *(new, 2026-06-22)*

> Keep adding investment/finance/economics **content** on the working platform — every feature
> answerable from licensed, point-in-time, **cited** data, combined by the multi-agent layer, with
> **live provenance + evidence**. Full research + feature→data→API map + the policy on estimates/
> guardrail is in **[`DATA_EXPANSION.md`](./DATA_EXPANSION.md)** — read it before any CE task.
>
> **Strategy:** maximize EXISTING free upstreams first (Wave 1 — no new API, fully sourced), then the
> **confirmed** new upstreams (Wave 2 — see Open Questions in DATA_EXPANSION §E; do NOT integrate a new
> upstream until the user confirms its spec/coverage). Each CE task = new connector + manifest entry (or
> store + compute) · unit tests · an eval scenario · agent tool-use · provenance/evidence wired · docs +
> roadmap updated (DoD §7). One task per PR; verify each end-to-end before the next.

- ✅ **CAT · 카테고리화 + 개별 툴 선택 (builder UX).** The agent builder now groups tools by **user-facing
  category** (금융시장 현황·종목 재무분석·밸류에이션·공시·문서·투자거장·수급·거시경제·뉴스룸·스크리너) and lets
  the user pick **individual tools** — never by upstream API. Connectors stay the data-plane routing unit;
  a single `Category` enum + `CATEGORIES` metadata + a `_CATEGORY` map in `catalog.py` stamp every resource
  (load **fails** if a tool is uncategorized → all future tools auto-follow the rule). `/catalog` exposes
  `categories` + a `category` per resource; studio-api `/connectors` returns `categories → tools`
  (fully-qualified ids); `filter_tools` matches tool-name / category / connector; `data_sources` stores
  individual tool ids ([] = unrestricted). +4 tests (datasets +2, agent +1 ext, studio +1). 🔴
- ✅ **BOARD-EDIT · 핀 에셋 title/description 인라인 편집.** Every pinned asset (chart/source/text) on the
  canvas now has a **click-to-edit title** (card header) + an editable **description** row ("＋ 설명 추가") —
  inline (no modal): click → input, Enter/blur saves, Esc cancels. Persisted via the existing
  `PATCH /board/{id}` spec merge (description lives in the spec JSON; title also updates the card). web
  `BoardCanvas` `InlineEdit`. **+ rich-text memo:** text blocks are now **markdown** — render formatted
  (react-markdown: 제목·굵게·목록·링크·표), click to edit the source, blur to save (TextBlock).
- ✅ **BOARD · 다중 보드 + 무엇이든 pin + 노션형 캔버스.** The pinboard became the differentiator surface:
  (1) **multiple named boards** (`Board` table; `/boards` CRUD; tab switcher + new/rename/delete); (2) **pin
  anything** — charts/tables **and source/evidence/provenance cards** (SourceCard 📌 → `kind:"source"` pin)
  **and writable text blocks** (`kind:"text"`); (3) a **board picker** on pin (multi-select boards or create
  one inline); (4) a **Notion-like free canvas** — `react-rnd` drag + resize, per-item layout (x/y/w/h)
  persisted, editable memo blocks. `PinnedArtifact` gained `board_id`+layout (idempotent ALTER-COLUMN
  migration keeps existing data). studio +2 tests (multi-pin/layout/source/text + scoped). web `BoardCanvas`
  + `PinPicker`. *(canvas rich-text is a textarea for now; block-level rich editing can follow.)*
- ✅ **FIX · 차트 타입 (돈=막대) + 출처 2섹션.** (1) Money-amount series (매출·순이익) now render as a
  **bar/histogram** chart, not a line — the artifact builder flags `chart_style="bar"` (ratios/prices stay
  line/candle); web TradeChart honors it. (2) Chat sources no longer "shrink" when the answer finishes —
  split into **답변에 사용된 출처** (cited) + a collapsible **참고한 모든 출처** (every consulted source),
  so the full sweep stays visible. +1 agent test. *(pin-everything + multi-board canvas = next phase)*
- ✅ **FIX · 백그라운드 생성 + 이어보기 (background runs).** Generation was tied to the browser's SSE
  connection — leaving a chat mid-answer cancelled it and lost the turn. Now a chat turn runs as a
  server-side **Run** (`studio-api/runs.py`): the agent-engine stream is driven by a detached background
  task that buffers every event and persists the assistant message on completion, independent of the
  client. `/chat/stream` just *tails* the run; `/conversations/{id}/active-run` + `/runs/{id}/stream`
  let a re-entry **resume live** (replay buffer → continue). Web tracks the displayed vs streaming
  conversation so leaving stops rendering (server keeps going) and returning re-tails. In-memory per
  process (survives client disconnect within a session). +1 studio test (run survives leave + resumes).
- ✅ **FIX · RAG 중복 제거 (corpus dedup).** The default in-memory vector store appended on every
  ingest, so a re-run pipeline duplicated news/filing chunks each sweep (retrieval then returns repeated
  passages). Fix: `MemoryStore.upsert` now dedups by chunk id (replace-in-place, matching pgvector's
  `ON CONFLICT DO UPDATE`), and news/filing docs carry a **stable `doc_id`** (news=url, filing=accession:page)
  so re-ingest upserts deterministically instead of relying on a text hash. +1 rag test.
- ✅ **FIX · 홈 프롬프트 폭포수 (waterfall hints).** Chat empty-state now shows the prompt-library
  examples rising in a seamless infinite loop (CSS transform marquee, two copies → translateY -50%),
  with a top/bottom fade mask. **Hover/focus pauses** it (key UX). Each chip shows the prompt's short
  summary (description); clicking drops the FULL prompt into the composer (not sent) → the {TICKER}
  fill bar appears to scope + send. Pulls live from `/prompts/community`; falls back to static chips if
  unloaded; respects prefers-reduced-motion. (web `PromptWaterfall`.)
- ✅ **FIX · 대화 기억 (follow-up context).** A follow-up ('배당률은?', '그 회사 주가는?') lost the
  subject because `analyze_task` (the intake) only saw the latest message — so it clarified or routed
  with no company even though the web sends full history and the planner already resolves references.
  Fix: pass the conversation into `analyze_task`; the intake prompt now carries a recent transcript and
  resolves follow-up references (inherits the earlier company/topic) instead of clarifying. +1 agent test.
- ✅ **FIX · 공시 본문 검색 (DART narrative).** Two real bugs surfaced by "find the filing passage that
  mentions 공급망/AI 수요": (1) KR `filings` ignored `filing_type` and returned date-ordered 지분/소유
  noise — now ranks 정기보고서·주요사항·감사 ahead of ownership reports + honors `filing_type`. (2) Filing
  narrative was only searchable if the opt-in `filing_text` pipeline had pre-run for that ticker → empty
  corpus for ad-hoc questions. New `datasets_store__filing_search` (`GET /filings/search`) does
  **on-demand RAG ingest**: search the corpus ticker-scoped → if empty, fetch+index that company's recent
  filings (the statement-bearing 사업/분기보고서, which carry 위험요소·사업의 내용) → search again; returns
  the RAG `{hits}` shape so each passage is cited + evidence-highlighted. +2 datasets tests, +1 eval. 🔴
- 🚧 **CE-0 · Broad backfill foundation.** Make the store deep + easy to fill (prerequisite for
  screener/quant/backtest/heatmap). **Code done:** prices pipeline depth is configurable
  (`PRICES_BACKFILL_YEARS`, default **5y**) so `PriceBar` holds enough history; admin backfill gains a
  one-click **★ 전체 유니버스** option (runs the scheduler's multi-preset spec — S&P500+KOSPI200+KOSDAQ150
  — through the storage pipelines); coverage shown in admin Data. +1 datasets test. **Operator step:**
  trigger the full-universe backfill (admin → Pipelines) or enable the scheduler; ~850 tickers × deep
  prices/financials is long on SQLite (WAL helps; Postgres for prod). *(no new upstream)*

**Wave 1 — existing/free data, new compute (fully cited, fastest):**
- ✅ **CE-1 · 자산군 (cross-asset).** New `yahoo__asset_classes` resource (`GET /market/asset-classes`):
  curated index/rates/commodity/FX/crypto proxy tickers → snapshot (level + day change) via the existing
  Yahoo provider, grouped, best-effort per member (failures dropped, never faked). Catalog/MCP/agent
  wired; agent-engine renders it as a sourced **table artifact** (자산군 현황). +2 tests (datasets +
  agent), +1 eval scenario. *(no new upstream)*
- ✅ **CE-COMMODITY · 원자재 시세 패널.** New `yahoo__commodities` (`GET /market/commodities`): curated
  commodity futures grouped 귀금속(금·은·백금·팔라듐)·산업금속(구리)·에너지(WTI·브렌트·천연가스·가솔린)·
  농산물(옥수수·밀·대두·설탕·커피·면화) → level + day change via the Yahoo provider, best-effort (drop on
  fail). agent renders a sourced grouped table. **DRAM/메모리 현물가는 무료 소스가 없어 미포함**(TrendForce/
  DRAMeXchange 유료) — 날조하지 않음; 필요 시 유료 소스 연동이 별도 과제. +2 tests (datasets+agent),
  live-verified. *(no new upstream.)*
- ✅ **CE-2 · 섹터 히트맵 (US).** New `yahoo__sector_heatmap` resource (`GET /market/sectors`): the 11
  SPDR Select Sector ETFs (XLK/XLF/XLV/…) → per-sector day change via the existing Yahoo prices provider,
  ranked leaders→laggards, best-effort (failed ETFs dropped, never faked). Catalog/MCP/agent wired;
  agent-engine renders a sourced **table artifact** (섹터 히트맵). +3 tests (datasets +2, agent +1),
  +1 eval scenario. *(no new upstream; KR sector indices = Wave 2, needs KRX/KIS.)*
- ✅ **CE-3 · 거장 매매 + 공통 보유종목.** Extended the SEC 13F provider with `by_filer_quarters`
  (reads the two most recent distinct reporting periods from the submissions block, skipping amendment
  dupes) → two new resources: `sec_edgar__guru_trades` (`GET /gurus/trades?slug=`) diffs the latest vs
  prior quarter into discrete moves **신규/추가/축소/전량매도** with share+value deltas, each cited to its
  13F accession; `sec_edgar__guru_common` (`GET /gurus/common`) intersects latest holdings across the
  curated gurus (best-effort, failed filers dropped) ranked by holder count. Catalog/MCP/agent wired;
  agent-engine renders both as sourced **table artifacts** (거장 매매내역 / 거장 공통 보유종목, $B/$M
  abbreviation). +5 tests (datasets +3, agent +2), +2 eval scenarios. *(no new upstream — SEC keyless)*
- ✅ **CE-4 · 종목 내러티브 / 관전 포인트.** Agent-engine capability (no new datasets endpoint — respects
  per-connector entitlement; synthesis stays in Gemini). Intake (LLM) gains a `narrative` flag → for a
  holistic company-story request it skips clarify, gathers across the company's facts/financials/
  valuation/filings/news via the normal entitled tool flow, and synthesizes a **structured, sourced**
  내러티브 in five sections (사업 개요·최근 실적·재무·밸류에이션·최근 이슈·관전 포인트), each claim cited [n];
  '관전 포인트' is descriptive monitoring only (guardrail: no forecast/target). `build_narrative_artifact`
  deterministically splits the answer into a pinnable **narrative artifact** (web `NarrativeArtifact`
  card). +2 agent tests, +1 eval scenario. *(no new upstream)*
- ✅ **CE-5 · 밸류에이션 모델 (DCF/DDM/RIM).** New `datasets_store__valuation` (`GET /valuation?model=`):
  a **transparent, user-input calculator** — base figures (FCF / dividend / book value+ROE) pulled from the
  company's real financials (sourced + as-of), the projection is the arithmetic of the caller's assumptions
  (growth/discount/years/terminal). DCF (two-stage + Gordon terminal), DDM (Gordon, user D0), RIM (residual
  income). Returns the **full breakdown + a disclaimer** ("가정 기반 계산 — 예측·목표가 아님"); insufficient
  data → honest note, never fabricated; bad math (discount ≤ terminal) → 400. agent-engine renders a sourced
  table; the guardrail still refuses the agent *volunteering* a target. +3 tests (datasets 2, agent 1),
  +1 eval. *(no new upstream)*
- ✅ **CE-6 · 퀀트 탐색 + 스크리너 확장.** New `datasets_store__quant_screen` (`POST /quant/screen`):
  computes a descriptive **factor set** per ticker from the ingested store (FinancialFact ⨝ PriceBar) —
  valuation (PE/PB/PS), quality (ROE/net·gross margin), growth (revenue_growth), size (market_cap),
  fcf_yield, and price momentum (return_window / pct_from_high / 52w high·low) — then **filters by any
  factor + ranks**. Cross-sectional description over ingested data (no forecasts; missing inputs → null,
  never faked). agent-engine renders a sourced ranked table. +2 tests (datasets 1, agent 1), +1 eval.
  *(no new upstream; quality scales with backfill coverage.)*
- ✅ **CE-7 · 백테스터.** New `datasets_store__backtest` (`POST /backtest`): buy-and-hold backtest of a
  weighted portfolio over ingested daily closes → **equity curve + total return / CAGR / volatility /
  max drawdown**, optionally vs a benchmark (rebased). Strictly descriptive past performance — no
  forecast/advice; missing price coverage → honest note (never fabricated). agent-engine renders the
  equity curve (portfolio + benchmark) as a timeseries; new **포트폴리오** category. +2 tests (datasets 1,
  agent 1), +1 eval. *(no new upstream; depends on PriceBar backfill.)*
- ✅ **CE-8 · 포트폴리오 (대시보드/분석).** New `Portfolio`/`Holding` product model in studio-api (per-user,
  new tables → create_all) + CRUD (`/portfolios` …) + a live **analytics** endpoint: values the book via
  the gateway (`/prices/snapshot` per holding, concurrent), computes **allocation + 평가손익**, and
  **backtests the current allocation** via the gateway `/backtest` (equity curve + metrics). Web
  `PortfolioPanel` (new **포트폴리오** rail view): manage holdings, live value/weight/gain table, backtest
  curve. Descriptive only; all data gateway-entitled. +1 studio test (CRUD + analytics + scoping). 🔵→✅
- ✅ **CE-9 · 거시 확장.** Broadened the DBnomics indicator catalog (+ industrial production, labor
  participation, 3M rate) and tagged every indicator with a **group/하위요인** (물가/고용/성장/금리) + region;
  `economic_indicators` now browses by `region`/`group` (열람). New **`fred__macro_panel`** (`GET
  /macro/panel?region=`): a 국가경제 snapshot — latest value + prior + change per indicator (concurrent,
  best-effort; failed series dropped, never faked), grouped. agent-engine renders a sourced panel table.
  +2 tests (datasets 1, agent 1), +1 eval. *(no new upstream; cycle/regime composites deferred — they
  verge on interpretation, kept to descriptive change.)*
- ✅ **CE-10 · 실시간 내러티브.** Two parts over the existing news ingestion: (1) a deterministic **news
  digest artifact** — `google_news__news` results → a sourced, pinnable table (헤드라인·발행사·날짜);
  (2) an intake **`news_brief`** flag + `_NEWS_BRIEF_GUIDE` → for a 시황/뉴스 브리핑 request the agent
  gathers recent news and synthesizes a **structured, sourced news narrative** (핵심 흐름·주요 헤드라인·
  맥락·지켜볼 점, each cited; descriptive — no forecast/advice), parsed into a pinnable narrative card.
  +1 agent test (digest table), +1 eval. *(no new upstream; reuses CE-4 narrative wiring.)*

**Wave 2 — new upstreams** *(build start ON HOLD per user; CE-11 upstream + estimates policy CONFIRMED — DATA_EXPANSION §E)*:
- 🚧 **CE-11 · 컨센서스 추정치 · 실적 캘린더** via **FMP** *(key provided; live-verified)*. New `fmp` connector:
  `fmp__consensus_estimates` (`/estimates`) = analyst consensus revenue/EPS/net-income (annual/quarter)
  and `fmp__earnings_calendar` (`/earnings-calendar`) = consensus-vs-actual EPS/revenue (surprise),
  both shown as **third-party sourced data, never our forecast** (CLAUDE §5 / DATA_EXPANSION §E); agent
  renders sourced tables. **Deliberately NOT exposed:** price targets + buy/sell ratings (guardrail brand).
  **Tier-gated on this key (not built):** market movers (gainers/losers/actives) + economic calendar —
  FMP premium endpoints. +2 tests (datasets 1, agent 1), +1 eval. `FMP_API_KEY` in `.env.example`.
  - ⬜ **CE-11b · FMP 유료 확장** *(when the key upgrades to a paid plan, per user)*: market movers
    (gainers/losers/most-actives), economic calendar, and — if the trust policy permits — price-target /
    grades consensus shown strictly as third-party data. Same `fmp` connector; add resources + categories.
- 🚧 **CE-12 · KR 실시간 — 거래량 순위 + 투자자 수급** via **KIS** *(keys provided; live-verified)*. New `kis`
  connector w/ OAuth token (24h cached, rate-limit-aware): `kis__volume_rank` (`/kr/rankings/volume` =
  KR movers/활발 종목 — the movers FMP gated) and `kis__investor_flow` (`/kr/investor-flow` = 개인/외국인/
  기관 순매수 = 수급, KR differentiator). Descriptive realtime; agent renders sourced tables; categories
  market + gurus(수급). +2 tests (datasets 1, agent 1), +1 eval. `KIS_APP_KEY/SECRET` in `.env.example`.
  **Extended (live-verified):** `kis__fluctuation_rank` (`/kr/rankings/fluctuation` — 상승/하락률 순위
  = gainers/losers) + `kis__etf_nav` (`/kr/etf-nav` — ETF 현재가 vs NAV + 괴리율). Both render sourced
  tables. **KIS-PRICES (live-verified):** `KisPricesProvider` — a drop-in PricesProvider (realtime
  snapshot + paginated daily OHLCV) selected by `PRICES_PROVIDER_KR=kis`, so charts/snapshots/backtest/
  portfolio all use KIS realtime KR prices. +1 datasets test. **시총 순위 (live-verified):**
  `kis__market_cap_rank` (`/kr/rankings/market-cap` — KR 대형주 시총·시장 비중·등락). CE-12 KIS suite
  complete: 실시간 시세 · 거래량/등락률/시총 순위 · 투자자 수급 · ETF NAV.
- ⬜ **CE-13 · 실시간/프리미엄 뉴스** via the confirmed news provider (Finnhub/Benzinga/Polygon). 🔴❓
- ✅ **CE-14 · IR자료실 + 밸류체인.** (1) **IR 자료실** — `datasets_store__ir_materials` (`/filings/ir`):
  IR/실적 공시 목록 (US 8-K · KR 주요사항보고서) via the filings provider's type filter. (2) **밸류체인** —
  intake `value_chain` flag + `_VALUE_CHAIN_GUIDE`: for a 밸류체인/공급망 구조 request the agent gathers
  filings+news and synthesizes a structured map (핵심 사업·주요 공급사(상류)·주요 고객(하류)·경쟁사·밸류체인
  내 위치), each cited, **labelled 공시·뉴스 기반 LLM 추출(derived) — 확정 거래관계 아님**; parsed into a
  pinnable narrative card (reuses CE-4 wiring). No node-graph render (structured sections, per CLAUDE).
  +1 datasets test (IR market filter), +1 eval. *(no new upstream.)*
- ✅ **CE-HEALTH · Upstream API health in admin.** datasets `GET /admin/upstream-health` probes every
  connector's upstream (SEC/DART/Yahoo/DBnomics/ECOS/news) **lightly** (cheap GET, short timeout, no quota
  burn) → reachability, HTTP status, latency, and required-key presence (key value never exposed),
  classified **정상/불안정/키 없음/다운**. New admin **📡 Upstream** page renders the health table (refresh
  = re-probe). +1 datasets test. *(admin + datasets; FMP/KIS rows appear once those Wave-2 connectors land.)*

---

### Phase 1 · Platform Hardening & Quality (PH) — ✅ shipped *(see §1 summary; detail archived below)*

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
- ✅ **PH-PIPE · Periodic data pipelines + multi-pipeline scheduler + admin control.** The scheduler was
  "down" (defaulted disabled + empty universe) and only covered financials/news. Now there's a **declarative
  pipeline registry** (`app/pipelines.py`) — one source of truth for every periodic collector (what it
  fetches, from which source, into which store): `financials` (SEC/DART → financial_facts) · `prices` (Yahoo
  → **new `PriceBar`**) · `corp_actions` (Yahoo → **new `CorporateAction`**) · `news` + `filing_text` (→ RAG) ·
  `evidence_docs` (→ PDFs). The **scheduler** sweeps a preset-resolved universe through a configured pipeline
  set on an interval (`run_pipelines`, per-pipeline `IngestionJob` + per-ticker retry; one failure never sinks
  the rest); `status()` exposes state/cadence/scope/last-sweep. **Universes are fetched DYNAMICALLY** (no
  hardcoded lists): `us_sp500` (datahub CSV) · `us_all` (SEC company_tickers) · `kr_kospi200`/`kr_kosdaq150`
  (top-N by market cap via pykrx) · `kr_kospi_all`/`kr_kosdaq_all`; cached with a TTL, resolved fresh each
  sweep so membership stays current; on fetch failure it serves stale-cache-or-empty (never fabricates).
  `resolve_universe` is async and still accepts the legacy explicit spec. New **`PriceBar` + `CorporateAction`** stores +
  `prices_ingest.py` (the big "served but unstored" gap) + coverage in `store_stats`. **Admin Pipelines** page
  rebuilt: scheduler banner (state · 주기 · 대상 종목 · 마지막 스윕 + Run/Pause/Resume), **per-pipeline cards**
  (source → store flow · schedule · last run · rows · errors), and a **unified backfill** form (pick preset
  or custom tickers + pipeline checkboxes → `POST /admin/pipelines/run`). Enable via `SCHEDULER_ENABLED` or
  the Resume button. +5 datasets tests (116→121), +1 admin (16→17). *(datasets + admin)* *(Postgres/Redis +
  distributed queue = PH-11; per-pipeline confidence/alerting + cached price serving = follow-on.)*
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
  - ✅ **PH-13b · guardrail folded into the LLM intake — ALL regex deleted (invariant #9).** The keyword
    regex wrongly refused FACT requests that merely *mention* a restricted word in negation ("목표가는
    제시하지 말고…", "전망·매수의견은 넣지 말고 사실만"). Root cause: keyword matching can't read context.
    Fix per the product owner: **delete the regex entirely** and move the decision INTO the existing
    first-pass analysis layer. `agent.analyze_task` is now one Gemini call returning a `TaskIntake`
    (`restricted`+`score`+`category`+`reason` **and** `steps`+`plan`) — it judges **intent** (told that
    negated/excluded terms are ALLOWED) and refuses only when `restricted` AND `score ≥ guardrail_threshold`
    (0.6). `chat.stream_chat` + `run_agent` call it once at the boundary (refuse before touching the data
    plane). `guardrails.py` is gutted to just the refusal/disclaimer copy; `GeminiGuardrailer`/
    `StubGuardrailer`/the regex/`get_guardrailer` factory and the redundant `assess_budget`/`_llm_steps` are
    removed (the intake supersedes them). No keyword fallback — when there is no LLM (dev/CI stub), the
    intake allows with the default budget (production always runs Gemini). +3 agent tests + 2 eval scenarios.
    *(agent-engine)*
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
  *(Update — PH-13b: the budget call is now folded into the single `analyze_task` intake alongside the
  guardrail; the standalone `assess_budget`/`_llm_steps` were removed.)*
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
> 6. **PH-RAG** — unified RAG corpus. **SEC/DART filing text now comes from [PH-PROV3e]** (the cached
>    evidence PDFs → text → chunk·embed·index; one artifact = corpus + evidence). PH-RAG = umbrella for
>    other text (transcripts, PH-SOURCES) + news ✅.  *(was PH-2c)*
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
- 🔁 **PH-RAG · Unified RAG corpus ingestion** → **for SEC/DART filing text, now delivered by
  [PH-PROV3e](#) (text from the cached evidence PDFs — one artifact = corpus + evidence)**, instead of a
  separate `/filings/items` ingest. PH-RAG remains the umbrella for *other* text sources (earnings-call
  transcripts, PH-SOURCES alt-data) ingested through the same pipeline shape. *(was PH-2c.)*
- 🚧 **PH-DATA · Data-source coverage (Valley-benchmarked, provenance-differentiated).** *(approved
  2026-06-21)* Match the data BREADTH of competitor **Valley AI** (NeuroFusion / 월가아재), but cover only
  the **descriptive, sourceable** types and put our wedge on each: **every datum provenance-linked to the
  real filing (PROV3), and we never fabricate forecasts** (the guardrail is the brand). Valley's
  forecast/model features — **DCF/DDM/RIM/Reverse-DCF/NTM, analyst estimates/consensus** — we deliberately
  **do NOT** copy (they clash with "no forecasting/advice"); that refusal IS the differentiation.
  Prioritized gaps (each → connector + MCP tool + provenance):
  - ✅ **PH-DATA-1 · Superinvestor / "거장" portfolios** — `/gurus` (15 verified investors:
    Buffett/Burry/Ackman/Dalio/Klarman/Icahn/Marks/Cohen/…) → `?slug=` returns that filer's latest **13F**
    holdings via the existing provider, every position carrying its accession → cited to the SEC 13F. New
    MCP tool `sec_edgar__gurus`; verified live (Buffett → Amex/Coca-Cola/Apple). +1 test, eval +1, coverage
    "all 35". Cross-guru **common holdings** = a later add. *(Valley: 거장 매매/포트폴리오/공통보유종목)*
  - ✅ **PH-DATA-2 · Peer comparables** — `/comparables?tickers=AAPL,MSFT,GOOGL` returns each company's
    valuation multiples + margins/returns **side by side** (reuses `metrics_snapshot` per ticker, parallel;
    caller/agent supplies the peer set → no universe needed). Descriptive, derived from filings + price
    (no forecast). MCP tools `sec_edgar__comparables` + `opendart__comparables`; coverage "all 37"; +1 test,
    eval +1. *(Valley: 상대가치평가/historical multiples)*
  - ✅ **PH-DATA-3 · Corporate actions** — `/corporate-actions?ticker=` → dividends (ex-date+amount) + stock
    splits (ratio) from Yahoo events (US+KR). MCP tool `yahoo__corporate_actions`; data-card evidence
    (source+values+date; no document). coverage "all 38", +2 tests, eval +1. *(basic coverage
    every platform has; we lack it)*
  - ✅ **PH-DATA-4 · Economic indicators DB** — `/macro/indicators` → CPI/core-CPI/unemployment/payrolls/
    GDP/PCE/10Y/EU-HICP via **DBnomics** (keyless, cloud-safe; FRED is datacenter bot-walled). MCP tool
    `fred__economic_indicators`; data-card evidence (observations + `db.nomics.world` source link + as_of;
    "NA" dropped, never faked). coverage "all 39", +2 datasets +1 agent tests, eval +1. *(Valley: 경제지표 일정/열람
    ← next: PH-DATA-5)*
  - 🔁 **PH-DATA-5 · KPIs + earnings-call transcripts → RAG** = **PH-9**. *(Valley: KPI/실적·전망)*
    - ✅ **KPI extraction (slice 1).** `POST /agent/kpis` (agent-engine) → `rag__search` over the company's
      PROV3e filing-text corpus through the gateway → **Gemini structured extraction of REPORTED KPIs only**
      (no forecasts/targets — guardrail), each KPI **cited to its source passage + an `/evidence` text
      highlight** in the cached filing PDF. Returns a pinnable `kpi` table artifact + per-KPI citations.
      No key (stub) → returns the sourced passages, never fabricated KPIs (honesty). Proxied via studio-api
      `POST /kpis` (tenant key → entitled+metered) + web BFF `/api/kpis`. +5 agent +1 studio tests; also
      fixed studio-api test isolation (ephemeral DB) — 4 pre-existing rerun failures. *(eval is chat-path
      only; this is a dedicated endpoint, covered by unit tests.)*
    - ✅ **KPI UI.** New **지표(KPI)** desk view (`KpiPanel`): company search → pull reported KPIs → a
      pinnable `kpi` table card + per-KPI **source-preview cards** (open the same evidence viewer; highlight
      in the real filing). `ArtifactCard` now renders `kind=kpi|table` matrices, so a pinned KPI card shows
      on the Board too. Honest empty/no-key state drawn, not hidden.
    - ⬜ **Earnings-call transcripts (slice 2).** Needs a **licensed transcript source** (no current
      connector provides them; SeekingAlpha/Motley Fool are redistribution-restricted) → ingest via PH-RAG
      once a source is cleared. Deferred behind per-source legal clearance.
  - 🔁 **PH-DATA-6 · Technical indicators / sector heatmap** — computed from prices (descriptive). *(Valley:
    기술지표/섹터 히트맵)*  · short interest, ownership breakdown — later.
    - ✅ **Technical indicators (slice 1).** `/technical-indicators?ticker=&indicators=` computes
      **descriptive** overlays from the prices provider's real OHLCV (US+KR): SMA/EMA(n), RSI(14),
      MACD(12,26,9), Bollinger(20,2σ), realized volatility. Each series tagged source="computed from
      Yahoo Finance" + the price `as_of`; **labeled descriptive, never a signal/advice** (guardrail).
      Catalog `yahoo__technical_indicators`; data-card / chart-ready series (feeds PH-VIZ overlays).
    - ⬜ **Sector heatmap (slice 2).** Needs sector membership (sector-ETF set or GICS map) → per-sector
      return grid. Deferred until a sourced sector-classification input is wired.
  *(KR realtime/flow/rankings come via the KIS connector; estimates/valuation-models intentionally excluded.)*
- ✅ **PH-VIZ · Professional trader charts + chart-as-evidence** *(all 6 slices done)* — *(replaces the dependency-free SVG
  artifact chart with a real trading chart engine, and makes the chart itself a sourced, annotatable
  artifact the agent can drive)*. **Engine choice:** [TradingView **Lightweight Charts**](https://github.com/tradingview/lightweight-charts)
  (Apache-2.0, ~45 KB, **client-side canvas — no data egress, no paid API, keys stay server-side**): real
  candlestick/OHLC + volume histogram, line/area/baseline, crosshair, time & price scales, log/%
  scaling. Heavier TradingView *Advanced Charts* (free but license-gated, self-hosted) is a **later**
  option only if built-in drawing UX is required; default to Lightweight + custom primitives. **All chart
  rendering routes through one `<TradeChart>` component** (don't fork chart code per surface). Guardrail:
  **no forecast/projection lines, no price targets, no buy/sell signals on charts** — overlays are
  descriptive and labeled, and the refusal still shows.
  - ✅ **PH-VIZ-1 · Chart engine swap.** Added `lightweight-charts` (Apache-2.0); new `<TradeChart>` renders
    real **candlesticks + a volume pane** when an artifact carries OHLCV, else line series — crosshair,
    time/price scales, range selector (1M/3M/6M/1Y/5Y/MAX), log & %-rebase toggles. `ArtifactCard` delegates
    the chart view to it (the 표 toggle keeps the figures table). agent-engine emits a `candlestick` artifact
    with real OHLCV `candles` for prices (`Artifact.candles`/`ArtifactCandle`); +1 agent test (81→82).
  - ✅ **PH-VIZ-2 · Sourced event markers (chart = evidence).** The price (candlestick) artifact carries
    **sourced markers** gathered from the same turn's results — ex-dividends + splits (`corporate_actions`),
    earnings dates (`earnings`) — each with its source; the agent enriches the chart post-loop
    (`enrich_chart_markers`, snapped to the nearest bar in the renderer). Clicking a marker opens the
    existing **SourceViewer** (a data card with the event + source). Descriptive **period high/low price
    lines** drawn from the price data itself. +2 agent tests (82→84). *(filing/macro markers + shaded period
    bands = follow-on.)*
  - ✅ **PH-VIZ-3 · Agent-driven annotations (request → overlay).** `annotations.py`: when a price chart
    exists, **Gemini** reads the question + the real candle digest and returns a structured spec
    (`ChartAnnotations`: lines / hlines / vlines / zones / rebase / note) — no hardcoded keyword rules
    (invariant #9). Validated server-side: every point must fall **inside the chart's date range (no future
    = no projection)** and a sane price band, else dropped. `<TradeChart>` renders trend lines (2-pt line
    series), level lines (price lines), date/zone marks + a note caption. Gemini-only (stub = no-op).
    +3 agent tests (84→87). *(zone shading + cross-ticker rebase compare = follow-on.)*
  - ✅ **PH-VIZ-4 · Technical overlays on the chart.** PH-DATA-6's `/technical-indicators` result is
    shaped into `ChartOverlay`s (agent-engine `artifacts.py`): SMA/EMA/Bollinger as `pane=price` lines,
    RSI/MACD/volatility as `pane=sub`. `enrich_chart_overlays` folds a same-ticker technical artifact onto
    the price (candlestick) chart so the overlays render **on** the price; with no price chart this turn it
    renders standalone. `<TradeChart>` draws price-pane lines on the right scale and stacks each sub-pane in
    its own overlay scale band at the bottom (volume moved above the stack), with RSI 30/70 context bounds —
    descriptive labels, sourced "computed from Yahoo Finance", never a signal. Server-owned line colors;
    line/candle/overlay-only artifacts all supported. +3 agent tests (89→92). *(user drawing = PH-VIZ-5.)*
  - ✅ **PH-VIZ-5 · User drawing tools + pinnable annotated chart.** `<TradeChart>` gains a drawing
    toolbar (✏ 추세선 = two clicks → trend line · ─ 수평선 = one click → level · 🗑 지우기). Clicks convert
    pixel→(time, price) via the series, appending to a separate `user_annotations` (ChartAnnotations shape)
    kept distinct from agent `annotations` so a re-answer/refresh never clobbers them. Drawings render in
    every chart mode (candle/line/overlay-only). They **persist with the Board pin**: the spec carries
    `user_annotations`, a new `POST /board/{id}/annotate` saves edits to an already-pinned chart, and
    `refresh_pin` carries the drawings across a live data refresh. +1 studio-api test (36→37); web build green.
  - ✅ **PH-VIZ-6 · Chart snapshot as exportable evidence.** A 📸 PNG button on `<TradeChart>` calls
    Lightweight Charts' `takeScreenshot()` and composes it onto a self-describing canvas — a title header
    + a sourced footer (`{source} · as of {as_of} · value-graph`) at the chart's pixel resolution (dpr-aware)
    — then downloads it. The exported snapshot includes the user's drawings + agent annotations + indicator
    overlays, so any chart can be cited/shared like a source-preview card. Web build green. *(in-app cite to
    SourceViewer = follow-on.)*
- 🔁 **PH-THINK · Transparent multi-agent reasoning + live thinking stream** — the chat turn now narrates
  its reasoning to the user in real time, replacing the bare "…".
  - ✅ **Model tiering for quality.** Quality where the answer is READ, economy where it's MECHANICAL:
    intake/decisions = `AGENT_BUDGET_MODEL` (flash-lite); tool routing + annotations + KPI = `AGENT_MODEL`
    (flash); verify/confidence = `AGENT_REASONING_MODEL` (flash, bump to pro for stricter grounding);
    **synthesis/combiner/conceptual = `AGENT_SYNTHESIS_MODEL` = `gemini-pro-latest`** (the user-facing
    answer → deep tier). The A2A combiner now also receives the sub-agents' full tool-result history (not
    just notes) so pro grounds on real evidence. All env-overridable; stub backend = no LLM.
  - ✅ **Live thinking stream.** A new SSE `thinking` event (phase: analyze · plan · fetch · found ·
    synthesize) flows through `stream_chat`; the web renders a live panel (latest step spinning, earlier
    steps ✓) that collapses into "🧠 분석 과정 · N단계" after the answer. E.g. "요청을 분석하고 있어요 →
    {source} 살펴보는 중 → ✓ {source} · 근거 N건 확보 → 근거를 정리해 답변을 작성하는 중".
  - ✅ **Analyze-first phase (quality).** `analyze_task` (one cheap Gemini pass) sizes the step budget AND
    returns a short natural-language plan ("what I'll look up"), shown as thinking and **injected into the
    system prompt** so tool selection + synthesis follow it. Gemini-only (stub = budget only, no plan).
    +1 agent test (87→88). *(replaces the old `assess_budget` call in chat.)*
  - ✅ **Verify/refine pass (quality).** Before the forced synthesis, a reviewer pass (`refine_evidence`,
    Gemini) reads the gathered evidence and writes a short brief (which sources/figures to use, conflicts,
    a one-line outline) that's **injected into the synthesis prompt** + shown as a "근거를 교차검증하는 중…"
    thinking step. Gemini-only, best-effort (never blocks). +1 test (88→89).
  - ✅ **Per-source confidence scoring (quality).** The verify pass now does its grounding review AND
    scores **each source's confidence** (high|medium|low + a one-line why = how well it supports the
    question) in the **same Gemini call** (structured JSON, invalid values dropped — never guessed).
    Scores ride back on the citations; the web shows a **신뢰 높음/보통/낮음** chip on each source-preview
    card (with the rationale on hover) — the trust brand, descriptive, never a forecast. Gemini-only,
    best-effort. +1 agent test (92→93).
  - ✅ **Rich responder — mix sourced facts with analyst context (fixes "answers too rigid").** The old
    synthesis prompt said "위 데이터에**만** 근거해 **간결**하게" → terse data-dumps with no insight. Now a
    dedicated, configurable **response model** (`AGENT_SYNTHESIS_MODEL`, light flash-tier, temp 0.45)
    composes a rich answer that **mixes**: every specific NUMBER/date/fact stays sourced + cited `[n]`
    (invariant #1 — no fabricated figures), while the model adds analyst context/definitions/interpretation
    from its own expertise (descriptive; guardrail still bans forecast/advice). The intake also routes
    **conceptual/definitional questions** (`needs_data=false`) straight to a rich explanation, skipping the
    tool loop (no more doomed tool calls for "PER이 뭐야?"). +2 agent tests, +2 eval scenarios (conceptual,
    rich-mix). *(agent-engine: planner `_SYNTHESIS_PROMPT`, `analyze_task.needs_data`, chat/run_agent paths.)*
  - ✅ **Clarify-with-options (Claude-Code-style plan/ask).** When the intake judges a request broad/
    ambiguous, it returns `clarify` + 2-4 concrete `options` (`{label, description}`, `multi` if
    combinable) instead of guessing. `chat.stream_chat` emits a `clarify` SSE event and stops; the web
    renders the choices as **pickable chips** (single → runs immediately, multi → toggle + "선택한
    내용으로 진행 →"), and a pick composes a refined follow-up question (`{원래 질문} — {고른 항목들}`)
    that flows through the normal turn. Only fires when ≥2 options and not restricted; the LLM is told not
    to clarify already-specific/conceptual requests; `run_agent` (non-interactive/eval) ignores it. +2
    agent tests (94→96). *(agent-engine intake + chat; web `ClarifyChips`.)*
  - ✅ **Parallel multi-source gather (execute many at once).** The planner now uses Gemini **parallel
    function calling**: `GeminiPlanner.plan_batch` returns EVERY independent tool call the model emits in a
    step (capped at `_MAX_PARALLEL_CALLS=5`), and `chat.stream_chat` announces them all then fetches them
    **concurrently in one `asyncio.gather`** (a failed call never sinks the batch; citations stay
    deterministically ordered). The system prompt nudges the model to batch independent needs (price AND
    news AND financials, or one metric across several tickers) and only chain when a call depends on a
    prior result. Stuck-detection now compares the whole batch signature. Stub stays single-tool;
    `run_agent` uses the first call. +1 agent test (96→97). *(agent-engine planner + chat loop.)*
  - ✅ **Full A2A orchestrator + sub-agent cards.** The intake (`analyze_task`) now decides
    **decomposition**: a clear-but-complex, multi-facet request returns 2-4 focused `subtasks`
    (`{title, question}`). `orchestrator.run_subagent` runs each as a **headless gather loop** over the
    shared tools (own small budget `SUBAGENT_BUDGET=4`, itself fanning out parallel calls) — it collects
    sourced evidence + artifacts + a short note, NOT a final answer. `chat.stream_chat` dispatches all
    sub-agents **in parallel** (`asyncio.as_completed`), streams a live **`subagent` card** per facet
    (running → done with sources/steps count), unifies every facet's citations (global de-dup + [n]) and
    artifacts, then runs ONE **combiner** synthesis weaving all facets into a single cited answer (one
    voice). The web renders `SubAgentCards`. Decompose is gated (clear intent, not restricted/clarify/
    conceptual, ≥2 facets); clarify is preferred when intent is unclear. +3 agent tests (97→100), +1 eval
    scenario. *(agent-engine `orchestrator.py` + intake + chat; web `SubAgentCards`.)* This completes the
    "Claude Code for finance" loop: **analyze → propose/pick → decompose → execute many (parallel) →
    combine**, every figure sourced.
  - ✅ **Chat UX overhaul → Claude-like.** (1) **Markdown bug fixed** — `_chunks` did `text.split()`+rejoin,
    collapsing newlines so `###`/lists/paragraphs never rendered; now character-based (preserves newlines).
    (2) **Real token streaming** — `GeminiPlanner.stream_final` (`generate_content_stream`); `stream_chat`
    routes EVERY finalization (conceptual · loop · stuck · A2A combiner · fallback) through one streaming
    `_synthesize`, so answers appear incrementally. (3) **Concise** — `_SYNTHESIS_PROMPT` rewritten: length
    proportional to the question (1–3 sentences for simple facts), no unprompted history lectures. (4) **Live
    Context panel removed** — evidence woven directly under each answer as inline `SourceCard`s (click →
    viewer); pinning unchanged. (5) **Layout** — single centered conversation column (max-width 760),
    assistant text flush, user message a compact chip. +2 agent tests (100→102); web green. *(agent-engine + web)*
  - ⬜ **Follow-ons:** per-sub-agent confidence/verify pass on the unified evidence; sub-agent cards that
    expand to show each facet's own sources; orchestrator that spawns a follow-up round when a facet comes
    back thin; suggested follow-up prompts after an answer.
- ✅ **PH-ADMIN · Operations console overhaul** — admin rebuilt as a left-nav mission-control organized by
  operator job-to-be-done (replaces the top-down single page; drops sqladmin → fixes the raw-HTML tables).
  One shared design system (tokens · tables · forms · badges · progress · status dots · nav). admin 12→16.
  - ✅ **PH-ADMIN-1 · Fixed the broken table UI.** Removed sqladmin (its static assets didn't load behind the
    auth guard → unstyled raw HTML) and built **our own styled CRUD** (view · edit · create · delete) on the
    reflected tables; relative URLs only (proxy/tunnel-safe). Typed coercion via the reflected `Table`.
  - ✅ **PH-ADMIN-2 · Catalog view.** Live from `/catalog` + `/rag/info` + `/agent/info`: every connector
    (markets · license · keyless/key-required), each resource → REST path → **MCP tool**
    (`{connector}__{resource}`) + source, plus RAG + agent backends. Never hand-maintained. *(per-item "try
    it" probe = future.)*
  - ✅ **PH-ADMIN-3 · Pipelines board.** All ingest/precompute jobs as live progress cards (kind · market ·
    spec · status badge · done/total bar · rows · started · error), page auto-refreshes while running;
    trigger/pause/resume/self-test + RAG ingest/search controls. From `/admin/jobs`+`/admin/scheduler`+`/admin/universes`.
  - ✅ **PH-ADMIN-4 · Data & store health.** Ingestion-store coverage by market (empty-state drawn, not
    silent), RAG backends, stored-rows-per-table. *(evidence-doc cache size = future.)*
  - ✅ **PH-ADMIN-5 · Users, tenants & entitlements.** Control-plane tenants → projects → API keys →
    activations → usage + studio users (read-friendly, link into the DB browser to edit).
  - ✅ **PH-ADMIN-6 · Information architecture.** Left-nav console (Overview · Catalog · Pipelines · Data ·
    Users · DB browser) with a one-glance **Overview** (tiles + per-subsystem health dots + recent errors).
    *(admin is out-of-band; not in the request path.)*
- 🔁 **PH-9 · KPIs via Gemini (#22)** from earnings text (Gemini extraction + metering) → **delivered by
  PH-DATA-5 slice 1** (`/agent/kpis`). *(↳ PH-RAG text, now via PROV3e)*
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
