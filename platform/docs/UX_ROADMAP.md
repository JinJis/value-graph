# UX Roadmap — product milestones (UX-prioritised)

> **The build order, prioritised by user value, with the technical tasks each one pulls in.**
> Spec (what it feels like): [`UX_SPEC.md`](./UX_SPEC.md) · Architecture: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
> · Technical backlog & test totals: [`ROADMAP.md`](./ROADMAP.md) · Engineering rules: [`../CLAUDE.md`](../CLAUDE.md).
>
> This file **leads** product sequencing; `ROADMAP.md` remains the source of truth for low-level
> technical tasks (data-plane 501s, hardening) and test counts. Each milestone below names the
> `ROADMAP.md` items it depends on or completes.
>
> Status: ✅ done · 🚧 partial · ⬜ todo. **One milestone at a time, one task per PR.** Tag PRs with the
> milestone (e.g. `[U1-WATCHLIST-02]`). A milestone isn't done until its acceptance criteria pass + the
> global Definition of Done (`../CLAUDE.md` §9).

---

## Where we are

Built (see `ROADMAP.md` / `ARCHITECTURE.md`): data plane (US+KR), catalog/manifests, control-plane
gateway (tenancy·entitlement·metering), MCP, RAG, agent-engine (stub|gemini, guardrails, citations,
streaming chat), studio-api (provisioning, conversations, **agent builder F1**, **prompt library F2**),
web (chat + builder + prompt modals). The product **works** but reads as "a chatbot with a data-source
picker." Everything below converts it into the **research desk** of `UX_SPEC.md`.

## Priority at a glance

| # | Milestone | Pillar | Why this order | Subsumes / depends |
|---|---|---|---|---|
| **U1** | Watchlists & @groups | Pull→Push | Foundation — personalization unit everything else binds to | new |
| **U2** | Source-preview cards | Trust | Highest "not-a-chatbot" proof per unit effort; mostly independent | uses existing citations |
| **U3** | Inline live artifacts + Board | Trust | Makes answers persistent & visual | needs U2 legend |
| **U4** | Standing analysts (push) | Pull→Push | The reason to come back daily | needs U1; **subsumes F3 messengers** |
| **U5** | Gallery: clone/substitution + publish | Ecosystem | Network effects; generalises F1/F2 patterns | needs U1, U4 |
| **U0** | Onboarding (cold-start) | all | Assembles U1+gallery+analyst into < 90s first value | needs U1 (min), U5 (full) |

> Ship a **minimal onboarding** with U1 (search→favorite→seeded desk); finish the full hire-a-starter
> flow once U4/U5 exist. That's why U0 is numbered first conceptually but lands incrementally.

---

## U1 — Watchlists & @groups  ⬜  (foundation)
**Goal:** the user can **search any listed company, favorite it into a named group**, and `@`-tag that
group in the composer and the analyst builder.

**New work**
- **datasets:** a **company search/autocomplete** endpoint (name + ticker, per market). Today only
  `/company/facts/tickers` exists — add `GET /company/search?q=&market=` over a name index (SEC ticker
  file + DART corp list). Manifest entry + catalog so the gateway entitles it. *(new task; relates to
  ROADMAP data-plane.)*
- **studio-api:** `Watchlist { id, user_email, name(@handle), created_at }` +
  `WatchlistItem { id, watchlist_id, market, ticker, name }`. CRUD: `/watchlists`, `/watchlists/{id}`,
  add/remove items. A company may be in multiple groups.
- **agent-engine / studio-api:** resolve `@handle` in chat + builder → expand to the group's tickers
  before planning.
- **web:** ⭐ stock-search modal + a `⭐ 관심` rail screen (groups, rename=re-handle, merge, remove);
  `@` autocomplete in the composer.

**Acceptance:** search "삼성" → favorite into a new `@반도체바스켓` → ask "@반도체바스켓 시가총액 합" →
the agent resolves the group and answers for exactly those names, all sourced.

**Tasks (one PR each, tag `[U1-…]`):**
- [x] **U1-01 · datasets — company search.** ✅ `GET /company/search?q=&market=&limit=` over a
      name+ticker index (SEC company_tickers + DART corp list), returns `{name, ticker, market, cik}`.
      Shared `rank_company_matches` (exact→prefix→substring) used by both providers; manifest entries on
      `sec_edgar`+`opendart`, route, openapi schema, coverage.sh matrix. +3 datasets tests → datasets 67.
- [x] **U1-02 · studio-api — watchlist model + CRUD.** ✅ `Watchlist {id, user_email, name(@handle)}` +
      `WatchlistItem {id, watchlist_id, market, ticker, name}`. Endpoints: `GET/POST /watchlists`,
      `GET/PATCH/DELETE /watchlists/{id}`, `POST /watchlists/{id}/items`,
      `DELETE /watchlists/{id}/items/{item_id}`. Per-user scoped; unique @handle per user (409 on dup);
      add-item idempotent on (market,ticker); a company may be in many groups. +4 tests → studio-api 28.
- [x] **U1-03 · @handle resolution.** ✅ `groups.expand_text` / `resolve_messages` expand `@handle` →
      `@handle (handle = 삼성전자 [005930, KR], …)` in user chat turns **and** in an analyst's system
      prompt, before the turn reaches agent-engine. The original (bare-handle) message is what's
      persisted/shown; only the agent's copy is expanded. Unknown→"알 수 없는 관심 그룹", empty→"빈 그룹".
      +2 studio-api tests → studio-api 30.
- [ ] **U1-04 · web — search/favorite + 관심 rail + @ composer.** Stock-search modal (autocomplete →
      ⭐ favorite → pick/create group), the `⭐ 관심` rail screen (groups: rename=re-handle, merge,
      remove items), `@` autocomplete in the composer. BFF routes `/api/watchlists` (+`[id]`, items) +
      `/api/company/search`. Web build green; e2e covers create-group → @-reference in a chat turn.

---

## U2 — Source-preview cards  ⬜  (the signature; build right after U1, can parallelise)
**Goal:** every inline citation `[n]` opens a **type-aware preview** — filing (verbatim highlighted
span), price/metric (computation + next refresh), news (snippet + "context only") — each with a
freshness dot.

**New work**
- **datasets/rag:** citations must carry enough to render the preview — `source`, `url`, `as_of`,
  `doc_type`, and for filings a **page ref + verbatim span** (rag already stores section/accession;
  extend the connector + retrieval payload so the cited span is returned). *(ties to ROADMAP "keep
  provenance/trust envelope intact through RAG + agent outputs".)*
- **agent-engine:** enrich each citation object with `{type, span?, page?, as_of, freshness,
  next_expected_update?}`; freshness computed from `as_of` vs the disclosure calendar (calendar lands in
  U4 — until then compute from `as_of` only).
- **web:** the three preview-card variants (§5.3), hover (desktop) / tap (mobile), drag-to-pin; the **one
  trust legend** component (freshness + confidence chip border) reused everywhere.

**Acceptance:** in a real answer, hovering a filing citation shows the exact cited sentence highlighted
on its filing page with `as_of` + freshness; a price citation shows the connector + computation; a news
citation shows the snippet labelled "맥락 정보 — 전망 아님".

---

## U3 — Inline live artifacts + Board  ⬜
**Goal:** figures render as **interactive cards backed by connectors** (refreshable), gaps are drawn,
and cards can be **pinned to a Board** that auto-refreshes.

**New work**
- **agent-engine:** emit a typed **artifact spec** alongside prose (`{kind: timeseries|compare|table|
  mini-graph, series[], provenance[]}`); guardrail still renders **no** artifact for refused asks.
- **web:** artifact renderer (charts; R3F only where a graph view is warranted), `↻새로고침` re-calls the
  connector, `⇄표로 보기` toggle, dashed gap segments; **Board** screen = grid of pinned artifacts, each
  re-fetching on open with its own freshness line.
- **studio-api:** `PinnedArtifact { id, user_email, spec(JSON), created_at }` CRUD for the Board.

**Acceptance:** ask for a multi-name margin comparison → an interactive card with per-series sources +
freshness; pin it; reopen the Board next day and it shows refreshed values with a new `as_of`.

---

## U4 — Standing analysts (push): schedule · disclosure calendar · briefs · channels  ⬜  (subsumes F3)
**Goal:** an analyst **runs headless on a schedule or a disclosure event** and delivers a **brief** to the
in-app inbox and Telegram. *This is the daily reason to return.*

**New work**
- **datasets:** a **Disclosure Calendar** endpoint — per-company next expected filing/earnings date
  (`GET /calendar?ticker=&market=`), derived from filing cadence + known earnings dates (KR DART
  schedule, US 10-Q/10-K cadence). *(new task; the legacy "Disclosure Calendar" concept, reborn as a
  connector. Powers `next_expected_update` and the freshness `stale` state from U2.)*
- **studio-api:** extend `Agent` → `kind: chat|standing`, `target_watchlist_id`, `schedule(cron)`,
  `triggers(JSON)`, `channels(JSON)`, `output_format`. Add `AnalystRun` + `Brief { run_id, title, body,
  citations, read }`. A runner endpoint `POST /analysts/{id}/run` (also used by "미리보기 실행").
- **pipeline/scheduler:** the datasets scheduler (exists) gains an **analyst tick** that calls the
  studio-api runner for due analysts; disclosure-calendar events enqueue runs (D-3). *(ties to ROADMAP
  "per-tenant cost quotas/budgets" — meter headless runs.)*
- **agent-engine:** a headless run mode that produces the brief artifact (reuses the tool loop; output
  format = brief). Guardrails unchanged.
- **integrations (F3):** Telegram channel — `Integration` seam exists; connect bot → deliver brief card.
- **web:** standing-analyst builder additions (targets/schedule/triggers/channels, NL↔form, 미리보기) +
  the `🔔 브리프` inbox (read/unread) + deep-link from a brief line into the Desk pre-loaded.

**Acceptance:** create a standing analyst on `@반도체바스켓` at 08:00 + disclosure D-3 → the scheduler
runs it headless → a sourced brief appears in the inbox and (if connected) Telegram, with a header
stating why it fired; tapping a line opens the Desk in that context.

---

## U5 — Gallery: clone/substitution + publish-back  ⬜
**Goal:** browse published analysts, **clone** one (binding wizard re-maps its slots to *my* watchlist /
activations / channels → a personal instance with provenance), and **publish** my own (re-abstracted,
private data stripped).

**New work**
- **studio-api:** define the **AnalystTemplate slots** schema (§5.7); `GET /gallery`,
  `POST /gallery/{id}/clone` (idempotent, records `source_id`+`source_version` — mirrors prompt-import),
  `POST /analysts/{id}/publish` (re-abstract: strip `target_watchlist_id` → `targets` slot, derive
  `data_sources` from used connectors, compute `cost_estimate`, attach badges).
- **control-plane:** clone must check the user's **activations** per required connector; restricted feeds
  (`license.redistribution=false` → yahoo/news) trigger **BYO-key or skip**. *(completes ROADMAP
  "governance/licensing enforcement: redistribution rules, BYO-key fallback".)*
- **web:** Gallery grid (badges `sourced·no-forecast·auditable`, author, ★, clone count, cost) + the
  4-step clone wizard (§5.7) + a publish flow.

**Acceptance:** clone a gallery analyst that targets the author's basket → the wizard binds it to *my*
`@반도체바스켓`, flags `news` as restricted (BYO-key or skip), runs a preview, and the saved instance
records `source_id`; publishing my analyst produces a template with **no** private watchlist.

---

## U0 — Onboarding (cold-start)  ⬜  (incremental: min with U1, full after U5)
**Goal:** a new user reaches **first sourced value in < 90s** — pick market → search+favorite (or interest
chips) → hire a starter analyst → land on a **non-empty desk**.

**New work**
- **studio-api:** onboarding state on `User` (completed?); interest-chip → representative-tickers map;
  seed the first watchlist + (full version) bind a starter Gallery template.
- **web:** onboarding flow (market → chips/search → ⭐ → hire → seeded "내 관심 한눈에" artifact on the
  Desk). Minimal version (U1): market + search/favorite + seeded desk. Full version (post-U5): the
  hire-a-starter-analyst step using the clone wizard.

**Acceptance:** a brand-new Google login is never shown an empty desk; within the flow they create a
watchlist and (full) hire an analyst whose first brief is scheduled.

---

## Cross-cutting (always-on, from `ROADMAP.md`)
- **Trust envelope intact** through RAG + agent + artifacts + briefs (U2/U3 depend on it).
- **Per-tenant cost quotas/budgets** — meter headless analyst runs (U4) and clone previews.
- **"Not investment advice" + no forecasting** enforced at the agent boundary, **shown** in the UI (all U).
- **One Gemini router, one tenancy model** — no forks.
- **Productionization** (ROADMAP #23): Postgres + Redis (scheduler/quotas live here), CI, observability —
  required before external multi-tenant launch (esp. U4 scheduler + U5 gallery).

## Suggested sequence
**U1 → U2 → U3 → U4 → U5**, with **U0** shipped minimally alongside U1 and completed after U5. Pull each
milestone's per-service tasks into `ROADMAP.md` as they're picked up, and keep test totals there current.
