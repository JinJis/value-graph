# 🚀 [PRD] ValueGraph — Supply Chain Intelligence, Visualized

> **"Gemini-grade cross-verification of who supplies whom — drawn beautifully, with every gap shown honestly."**

| Field | Value |
|---|---|
| Doc version | **v5.0.0** |
| Date | 2026-06-02 |
| Status | Draft (paired with `ValueGraph_BUILD_PLAN.md` for execution) |
| Changes vs v4 | **Gemini-only** (all Anthropic/Claude model routing removed). Refined **Admin & Terminal flows** to match the canonical user journeys. Added **Disclosure Calendar** (per-company filing-schedule tracking) and **Live Context Feed** (news/interviews as context + CVE triggers, *not* prediction). **Community moved to Phase 2** — v1 is admin-driven. Companion **build plan** breaks every milestone into tagged, acceptance-tested tasks. |
| Audience | PO, engineers, data/AI engineers, **Claude Code** (the build tool) |

> **How to use these docs:** This PRD = the *what/why*. `ValueGraph_BUILD_PLAN.md` = the *ordered, tagged tasks + acceptance criteria*. Build one milestone at a time, one task per PR; check acceptance criteria before moving on.

---

## 0. TL;DR

ValueGraph is a **B2C, visualization-first tool that maps the real supply value chain of an industry** (e.g. AI Data Centers) as an interactive 3D node graph — companies as nodes (size = live market cap), supplier→customer trades as edges. The differentiator vs anything consumer-facing: a **Gemini-grade Cross-Verification Engine (CVE/VSCA)** that quantifies each supplier→customer relationship from public disclosures and reconciles conflicting signals, **plus radical honesty about uncertainty** — every figure shows its source, as-of date, freshness, **when it will next update**, and a confidence tier, and **data gaps are rendered visibly** so users see what's missing. We do **not** forecast; we show the present supply chain accurately, with its uncertainty made legible, refreshed when new filings drop.

**Three pillars:** **Quantify** (CVE/VSCA) · **Show the truth** (confidence + freshness + provenance, gaps drawn) · **Stay current** (disclosure-calendar-driven re-runs + a live context feed).

---

## 1. Naming

**ValueGraph** — *(placeholder name, to be revisited)* the industry's value chain, rendered as a navigable graph.

| Name | Surface | One-liner |
|---|---|---|
| **ValueGraph Studio** | Admin back-office | Build a theme, run CVE, process tickets, publish |
| **ValueGraph Terminal** | User front-end | 3D supply-chain canvas with evidence, freshness, next-update, live feed |
| **ValueGraph Engine** | Backend | Ingestion + **Cross-Verification Engine (CVE)** + graph store + scheduler |
| **CVE / VSCA** | Algorithm | Cross-Verification Engine; ValueGraph Supply Chain Algorithm (quantify + reconcile) |

---

## 2. Problem & target user

**Primary persona:** a retail investor (early-/mid-30s, KR + overseas equities, into AI semis / data centers) who wants to **see the real structure of a hot sector and know how much to trust each number.** Pain points: (1) value-chain links are guessed, 2nd/3rd-tier vendors invisible, link *strength* never shown; (2) sources are fragmented and multilingual (DART/EDGAR/EDINET, IR decks, news); (3) nobody flags staleness or certainty.

**Why now / why us:** AI semis & data centers dominate market attention; people want **industry structure**, not single tickers. Bloomberg's SPLC quantifies supply chains superbly but is ~$25k/yr, table-based, and opaque to a retail user. The gap ValueGraph fills: **professional-grade supply-chain data + best-in-class visualization + honest uncertainty + freshness you can see.**

---

## 3. Scope

### 3.1 In scope (v1)
- **Supply value chain only**: supplier→customer trades, the product behind each, the trade size, and the exposure % on each side.
- One flagship theme at launch (**AI Data Centers**).
- Confidence tiers + intervals, source provenance, as-of dates, **freshness + next-update**, and **visible gaps**.
- **Admin-driven** ticket filling (admin uploads filings/reports to resolve gaps).
- **Live Context Feed** (news / CEO interviews / filings) shown as context and used to trigger CVE re-runs.
- **Disclosure Calendar**: per-company filing-schedule tracking that drives "next update" and scheduled refreshes.

### 3.2 Out of scope
- ❌ **Prediction / forecasting / momentum / "expected upside"** — none. (Removed for accuracy, liability, regulation.) Live price/market cap is real-time *data*, not a forecast — that stays in.
- ❌ Trade execution / brokerage.
- ❌ `REVENUE_FLOW` / `INVESTS_IN` / `COMPETES_WITH` edges (schema-reserved, not built in v1).
- ⏭️ **Community contribution** (contributor submissions, reputation, reviewer tooling) — **Phase 2.** v1 seeds a complete flagship theme admin-only to avoid cold-start. (Architecture leaves the seam; see §7.)

### 3.3 Four core values
**Structure** (full supplier→customer topology) · **Strength** (quantified, reconciled link sizes) · **Honesty** (confidence + source + as-of + freshness; gaps shown) · **Currency** (refreshed when new disclosures land).

---

## 4. System architecture (Two-Track)

Producing data (Studio/Admin) and consuming it (Terminal/User) stay separated. (Phase-2 community would feed Staging through the same review seam.)

```
┌──────────────── VALUEGRAPH STUDIO (Admin) ───────────────────────────┐
│  Admin ⇄ Gemini Agent Orchestrator (LangGraph)                     │
│     │              │                                               │
│     │       ┌──────┴───────┐                                       │
│     │       │ CROSS-VERIFICATION ENGINE (CVE / VSCA)             │ │
│     │       │ ingest→extract→resolve→derive→reconcile→score→gap  │ │
│     │       └──────┬───────┘                                       │
│     │              ▼                                               │
│  Ticket queue ◄── auto gaps        Knowledge Graph                 │
│  (admin processes; unresolved          │                           │
│   states persisted too)           [ STAGING DB ]                   │
│     │                        (Neo4j + Postgres + Vector)           │
│     │                                  │                           │
│  Validation gate ──────────────► [🚀 Publish] ──┐                  │
└──────────────────────────────────────────────────│────────────────┘
                                                    ▼
┌──────────────── VALUEGRAPH TERMINAL (User) ──────────────────────────┐
│  [ PRODUCTION DB ] (read-only snapshot)                            │
│       │                                                            │
│  Next.js + React Three Fiber (WebGL 3D canvas, 60fps)              │
│  Macro → Depth → Flow → Node/Edge drilldown → Evidence/Freshness   │
│       ▲                                  │                         │
│  Live Market Feed (price/mktcap)   Right panel: Live Context Feed  │
│  Disclosure Calendar ─► "next update" + scheduled CVE re-runs      │
└────────────────────────────────────────────────────────────────────┘
```

**Hard invariants (never violate):**
- Terminal reads **Production only**. Staging / raw agent intermediates never exposed as fact.
- **Publish is an explicit human action.** No auto-publish.
- **Every exposed figure carries `source_id` + `as_of_date` + `next_expected_update` + `confidence` (+ interval).** Missing any → cannot Publish.
- **No number enters the graph without a `Source`.**
- LLM/API keys server-side only.

---

## 5. Data model — knowledge graph schema

Primary store **Neo4j**. Provenance + freshness are first-class.

### 5.1 Nodes
| Node | Key attributes |
|---|---|
| `Theme` | `name`, `depth_max`, `version`, `published_at`, `data_quality`{verified%, derived%, estimated%, gap%} |
| `Company` | `ticker`, `name`, `country`, `exchange`, `market_cap`(**live**), `price`(**live**), `sector`, `tier`, `fiscal_calendar`, `last_filing_date`, `next_filing_estimate` |
| `Division` | `name`, `revenue_share`%, `parent_company` |
| `Product` | `name`, `category`, `cost_bucket_hint` (COGS/CAPEX/R&D/SG&A) |
| `Source` | `type`(filing/IR/report/news/interview), `url`, `publisher`, `as_of_date`, `language`, `verification_status` |
| `Claim` | `relation`, `subject`, `object`, `value`, `unit`, `cost_bucket`, `as_of`, `source_id`, `extracted_by`, `text_span` |

### 5.2 Edges
| Edge | Direction | Key attributes |
|---|---|---|
| `HAS_DIVISION` | Company→Division | — |
| `PRODUCES` | Division→Product | `capacity`, `yield` |
| `SUPPLIES` (**core**) | Company→Company | `product_ref`, `trade_value`, `currency`, `supplier_rev_share`%, `customer_cost_share`%, `cost_bucket`, `confidence`, `confidence_interval`, `as_of_date`, `next_expected_update`, `freshness`, `gap`(bool) |
| `SUPPORTS` | Claim→SUPPLIES | `weight`, `agrees`(bool) |
| `SOURCED_FROM` | Claim→Source | `extracted_value` |

### 5.3 Validation-gate rule
Every quantitative `SUPPLIES` attribute MUST carry `as_of_date`, `next_expected_update`, `confidence` + `confidence_interval`, a `SUPPORTS→Claim→SOURCED_FROM→Source` chain, and a derived `freshness`.

---

## 6. Cross-Verification Engine (CVE) & VSCA

**Goal:** for each supplier→customer edge, produce a quantified trade value + both-sided exposure %, a confidence tier with interval, a freshness state, and a next-update date — by reconciling multiple public signals.

### 6.1 Governing principle — "one trade, two ledgers"
A trade A→C is the same dollar amount seen two ways:
- supplier (A): `trade_value = supplier_rev_share × Revenue_A`
- customer (C): `trade_value = customer_cost_share × CostBucket_C`

One disclosure yields `trade_value`; **both** let us **cross-check**. Three constraints sharpen estimates: **(1) 10% disclosure ⇒ an undisclosed customer is < 10%** (hard upper bound); **(2) conservation** (Σ shares per node ≤ 100%, + an "undisclosed remainder"); **(3) cost-bucket typing** (COGS/CAPEX/R&D/SG&A) to convert between ledgers correctly.

### 6.2 Pipeline (S0–S7) — full detail in `ValueGraph_BUILD_PLAN.md` M3
```
S0 Ingest      pull filings/IR/news (multilingual) → Source records
S1 Extract     MEDIUM model → atomic Claims with verbatim span
S2 Resolve     entity-resolve mentions → canonical Company (dict + embedding + LLM)
S3 Derive      VSCA math: complementary ledger side + cost-bucket
S4 Reconcile   cluster estimates, propagate constraints, DETECT CONFLICTS (flag, never average) → point + interval
S5 Estimate    VSCA-est (DEEP): suspected-but-unquantified edges → always `estimated` + wide interval + auto-ticket
S6 Score       confidence tier + interval + freshness + next_expected_update
S7 Gap-detect  emit tickets for estimated / conflict / stale / unclosed-conservation
```
Worked shape (S3): INTC discloses **21%** of revenue from HPQ → `trade_value = 0.21 × Rev_INTC` → `≈ 9.5%` of HPQ's COGS. Both sides populated from one disclosure.

**Confidence tiers:** `verified` (primary disclosure corroborated by ≥2 independent sources, or exact math from a primary filing) · `derived` (single disclosure + math) · `estimated` (algorithmic only). **Every value ships with an interval — never a bare point.**

**Cross-verification within Gemini:** "dual-verification" now means **Pro (DEEP) re-checks Flash (MEDIUM) extraction** on high-impact edges, plus **multi-source corroboration** — not two providers.

### 6.3 Cost-bucket typing
LOW/MEDIUM classifier + product→bucket rules map each trade to COGS/CAPEX/R&D/SG&A (HBM → customer COGS; fab equipment → CAPEX). Ambiguous → ticket.

### 6.4 Freshness model (real-time vs periodic)
Two clearly separated layers — **this is how we honor "investors need real-time" without forecasting:**
- **Real-time layer:** `price`, `market_cap` (live feed; node *size* reflects this).
- **Periodic layer:** relationships/shares/trade values — only as fresh as the last disclosure (usually quarterly).

`freshness` per periodic figure: `fresh` (<~30d) · `aging` · `stale` (past next-expected-filing) · `gap` (no data). The Terminal **always** shows it; a quarter-old number is labeled as such.

### 6.5 Confidence & gaps surfaced
Gaps (`estimated` / `conflict` / `stale` / unclosed-conservation) are both **ticketed** (Studio) and **drawn** (Terminal ghost edges). Re-running CVE after new evidence upgrades the edge and closes the ticket.

### 6.6 Disclosure Calendar (per-company refresh intelligence) — NEW
CVE is only as current as the filings it has seen, so ValueGraph tracks **when each company next discloses**:
- Each `Company` has a `fiscal_calendar` + `next_filing_estimate` (10-K/10-Q, 사업보고서/분기보고서, EDINET filings, earnings dates), learned from filing history + IR sources.
- Drives the **`next_expected_update`** on every figure ("next: 2026-Q2 earnings, est. Aug").
- Drives **scheduled CVE re-runs**: when a tracked company's filing is due/detected, enqueue a targeted re-ingest + CVE for the affected edges (admin re-publishes).
- Powers the Terminal **upcoming-update timeline** so users see when the map will refresh.

---

## 7. Community layer — Phase 2 (architecture seam only in v1)

v1 is admin-driven. Phase 2 opens gap-filling to a community: Viewer → Contributor (must attach a source) → Reviewer (reputation-gated) → Admin; ticket lifecycle gains SUBMITTED → SOURCE-CHECK (model re-verifies the URL actually contains the claimed value) → IN-REVIEW → ACCEPTED/REJECTED; sourced facts only; two-reviewer rule for high-impact edges; full audit trail. **v1 requirement:** keep the ticket + Source + Claim model and the review/publish seam clean so Phase 2 plugs in without rework. Deferred because of cold-start (need a complete flagship theme first).

---

## 8. Workflow 1 — ValueGraph Studio (Admin) — canonical 7-step flow

> All intermediates persist in **Staging** (incl. unresolved ticket states). Maps 1:1 to BUILD_PLAN M1–M4.

1. **Create a theme.** Admin names a theme (e.g. "AI Data Centers"), optionally uploads Additional Context (broker PDFs, seed tickers, industry reports). *(M1)*
2. **LLM blueprint analysis (iterate 2–3×).** Gemini (DEEP) analyzes the theme + context and produces a **structured blueprint** of everything needed to build the chain: candidate companies worldwide (KR/US/JP/CN/TW), their products/roles, the relationship types to populate, and the **required data points** per company. The blueprint is **re-fed to the model 2–3 rounds** to expand hidden vendors, dedupe, and fill missing fields, until convergence or a 3-round cap. *(M1)*
3. **Cut tickets → admin processes them.** Every required-but-missing data point becomes a structured **ticket** (what metric, which company/edge, why). The admin resolves a ticket by uploading the evidence — e.g. a company's **2026-Q1 financial filing, disclosures, broker reports** — which is stored as a `Source`. *(M2)*
4. **Iterate with CVE.** As evidence lands, the **Cross-Verification Engine** runs (extract → resolve → derive → reconcile → score), keeps **finding new gaps**, and **cuts more tickets** for the admin. Repeat 3–4. *(M2 + M3)*
5. **Everything is persisted; assemble the chain.** All steps and artifacts (nodes, edges, claims, sources, ticket states) save to the DB, versioned. When gaps reach the completeness threshold (or admin override), the publishable **supply-chain graph is assembled**. *(M4)*
6. **Unresolved tickets are first-class data.** The admin may be unable to close some tickets (info not found / not disclosed / paywalled / ambiguous). These are **persisted with a reason code and reused** by CVE — e.g. a "confirmed-undisclosed" mark sets the edge's 10% upper bound and confidence handling, and feeds future builds. *(M2 + M4)*
7. **Publish.** Once the chain passes the **validation gate** (every figure has source + as-of + next-update + confidence + interval), the admin **Publishes** → Staging syncs to Production (read-only, versioned). *(M4)*

**Studio screens:** Theme dashboard (data-quality meter) · Blueprint review (editable tree/table) · Agent/CVE console (run logs, reconciliation traces) · **Ticket queue & processing** (upload evidence, mark unresolvable w/ reason) · Source manager (provenance, as-of) · Publish console (validation report + diff).

---

## 9. Workflow 2 — ValueGraph Terminal (User) — canonical flow

> Reads **Production**. **No prediction.** Maps to BUILD_PLAN M5–M7.

1. **See the supply-chain node map.** Click a theme → dark 3D space; published companies render as nodes (**size = live market cap**), connected by **SUPPLIES edges** with **directional particle flow** (thickness = trade value). A theme data-quality meter is visible. *(M5)*
2. **Start simple, drill into evidence.** Default view emphasizes the *flow*. Clicking a **node** opens a **Company Drawer** (divisions → products → who-buys-each + share; live price/mktcap shown separately from periodic figures). Clicking a **product** highlights only its customer edges. Clicking an **edge** opens an **inspector** showing the supporting claims, both-ledger shares, and the reconciliation summary (incl. any conflict). Every figure carries a **provenance card**: value **+ interval**, confidence chip, **"as of 2026-Q1 · 80 days old"**, and a **source link** to the actual document. Confidence is encoded on edges (solid/dashed/ghost), freshness as a green/amber/red dot, and **gaps are drawn as ghost "?" edges** (never hidden). *(M5 + M6)*
3. **See when data will update.** Each figure/edge shows its **`next_expected_update`** (driven by the Disclosure Calendar, §6.6), and the theme shows an **upcoming-update timeline** — because CVE refreshes when new filings drop, and per-company filing schedules are tracked. *(M7)*
4. **Right-panel Live Context Feed.** A continuously updating stream of **news, CEO interviews, and new filings**, entity-linked to nodes (selecting a node filters the feed to it). Clicking an item shows its source. **Explicitly labeled context — no scoring, no momentum, no forecasting.** New filings here also **trigger CVE re-runs** behind the scenes. *(M6 + M7)*

---

## 10. Non-functional & compliance

- **Performance:** 60fps with hundreds of nodes + particle flows; **WebGL instanced meshes, no DOM nodes**; LOD + frustum culling beyond ~1k nodes; Macro→Micro & depth-slider < 100ms.
- **Legal (review with a professional — we are not lawyers):** "**Not investment advice**" disclaimer. Respect source ToS/robots; **don't redistribute filing/report full text** — store extracted numbers + source link, minimal quoting. Live price/market cap needs a **licensed feed** (delayed vs real-time, redistribution rights); default to delayed until confirmed. Feed items shown as context only.
- **Security:** Studio and Terminal on separate auth domains; Production read-only from Terminal; keys server-side only. PII/billing isolated in Postgres; payments via a PG provider.

---

## 11. Tech stack (Gemini-only)

| Layer | Choice | Reason |
|---|---|---|
| Graph DB | **Neo4j** | depth traversal + provenance graph (Cypher) |
| Vector DB | **Pinecone** (or pgvector) | entity resolution + claim dedup |
| RDBMS | **PostgreSQL** | users, tickets, billing, job state, disclosure calendar |
| Cache/Queue | **Redis** | job queue, live-feed cache, rate limiting |
| Backend | **Python FastAPI + LangGraph** | CVE orchestration + Gemini routing |
| **LLM** | **Google Gemini only** | single-provider simplicity |
| Frontend | **Next.js + React Three Fiber (Three.js)** | WebGL 3D 60fps |
| Client state | Zustand / TanStack Query | canvas + server sync |
| Infra | Docker + object storage (filings/PDFs) | — |

**Gemini routing by tier** (IDs as of 2026-06; verify before changing):

| Tier | Role | Gemini model |
|---|---|---|
| `DEEP` | blueprint analysis, hidden-vendor inference, VSCA-est, Pro re-check of extractions | `gemini-3.1-pro-preview` |
| `MEDIUM` | precise claim extraction from filings (PDF/img), cost-bucket typing | `gemini-3.5-flash` |
| `LOW` | source normalization, entity-resolution hints, JSON/schema formatting, feed tagging | `gemini-3.1-flash-lite` |
| `RESEARCH` | broad worldwide constituent discovery | **Gemini Deep Research Agent** (preview) |

---

## 12. Roadmap (see `ValueGraph_BUILD_PLAN.md` for tagged tasks + acceptance criteria)

| Milestone | Focus | Maps to flow |
|---|---|---|
| **M0** | Scaffolding, infra (Neo4j/PG/Redis), schema package, Gemini router | — |
| **M1** | Theme creation + **blueprint analysis (iterate 2–3×)** + discovery | Admin 1–2 |
| **M2** | **Ticket generation + admin processing** + unresolved-state persistence | Admin 3, 6 |
| **M3** | **CVE/VSCA** (S0–S7) — *critical path* | Admin 4 |
| **M4** | Persistence + graph assembly + validation gate + **Publish** | Admin 5, 7 |
| **M5** | Terminal **macro map** (flow, depth, confidence/freshness encoding) | User 1–2 |
| **M6** | Terminal **drilldown + evidence** + **Live Context Feed** | User 2, 4 |
| **M7** | **Disclosure Calendar** + next-update UI + scheduled CVE re-runs | User 3 |
| **Phase 2** | Community contribution (submissions, reputation, review) | — |

Critical path: M0→M1→M2→M3→M4. M5/M6 can begin once M4 publishes a sample theme. M7 builds on M3 + M6.

---

## 13. KPIs
**Data quality:** % edges `verified`, avg interval width, conflict rate, gap-closure over time. **Freshness:** % figures within their expected-update window, stale-edge count, time-to-refresh after a filing. **Engagement:** depth-slider use, drilldowns/session, provenance-card opens, feed interactions. **Performance:** avg canvas fps, Macro→Micro latency.

---

## 14. Open issues
1. **Market-data vendor & licensing** (real-time vs delayed; redistribution rights).
2. **VSCA-est validation** — back-test estimated edges against later-disclosed truth (sanity of the *algorithm*, not forecasting).
3. **Vector DB** — Pinecone (managed) vs pgvector (Postgres-unified).
4. **Multilingual parse quality** (CN/JP) thresholds before an edge is publishable.
5. **Disclosure-calendar accuracy** — how to reliably learn/maintain per-company filing dates across markets.
6. **Legal review** of scraping/redistribution per target market.
7. **Phase-2 trigger** — completeness bar for the flagship theme before opening community.

---

*End. Bump version/date on change. Tasks: `ValueGraph_BUILD_PLAN.md`. Engineering rules: `CLAUDE.md`.*
