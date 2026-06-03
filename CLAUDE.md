# CLAUDE.md — ValueGraph

> Guidance for Claude Code in this repo.
> **Spec (what/why):** `ValueGraph_PRD_v5.md` · **Tasks (how/when):** `ValueGraph_BUILD_PLAN.md` · this file = engineering rules (how).
> **Always pull your next task from `ValueGraph_BUILD_PLAN.md`.** Build one milestone at a time, one task per PR, and don't mark a task done until every acceptance criterion passes. Reference the task tag (e.g. `[M3-REC-04]`) in the branch, commits, and PR title.

---

## 1. What we're building

**ValueGraph** = a **B2C, visualization-first supply-chain intelligence tool**. Given an industry (e.g. "AI Data Centers") it maps listed companies as **nodes** (size = live market cap) and **supplier→customer trades** as **edges**, in a WebGL 3D canvas. Differentiators:
1. A **Gemini-grade Cross-Verification Engine (CVE/VSCA)** quantifying each supplier→customer relationship from public disclosures, reconciling conflicting signals.
2. **Radical honesty about uncertainty** — every figure shows source, as-of date, freshness, **next-update**, confidence tier (+ interval); **gaps are drawn, not hidden.**
3. **Staying current** — a per-company **Disclosure Calendar** drives scheduled CVE re-runs; a **Live Context Feed** (news/interviews/filings) gives context and triggers refreshes.

Name = ValueGraph (placeholder, to be revisited): the value chain rendered as a navigable graph.

### ⚠️ Scope (read before building anything)
- **IN (v1):** supply value chain only (supplier→customer trades, the product, trade size, both-sided exposure %), confidence/freshness/provenance, **admin-driven** ticket filling, Disclosure Calendar, Live Context Feed.
- **OUT (v1):** ❌ **prediction / forecasting / momentum of any kind** — do NOT build Predict, ghost-node-as-forecast, "expected upside," scored feeds, etc. ❌ trade execution. ❌ `REVENUE_FLOW`/`INVESTS_IN`/`COMPETES_WITH` edges (schema-reserved). ⏭️ **community contribution = Phase 2** (keep the seam clean; don't build it in v1).
- **"Real-time" ≠ prediction.** Live price/market cap IS in scope. The Live Context Feed shows raw items only — no scoring/forecasting.

### Models: Gemini only
All LLM calls go through the central router (`services/engine/llm/router.py`); IDs from env. **No other provider.**
| Tier | Job | Model (env-overridable) |
|---|---|---|
| `DEEP` | blueprint analysis, hidden-vendor inference, VSCA-est, Pro re-check of extractions | `gemini-3.1-pro-preview` |
| `MEDIUM` | precise claim extraction from filings (PDF/img), cost-bucket typing | `gemini-3.5-flash` |
| `LOW` | source normalization, entity-resolution hints, JSON formatting, feed tagging | `gemini-3.1-flash-lite` |
| `RESEARCH` | broad worldwide constituent discovery | Gemini Deep Research Agent (preview) |

### Two-Track architecture (memorize)
```
Studio (Admin) → STAGING DB --[explicit Publish]--> PRODUCTION DB → Terminal (User)
  build · run CVE · process tickets   (mutable)            (read-only)        3D canvas
```
**Hard invariants — never violate:**
1. Terminal reads **Production only**. Never expose Staging / raw agent intermediates as fact.
2. **Publish is an explicit human action.** No auto-publish.
3. Every exposed figure carries `source_id` + `as_of_date` + `next_expected_update` + `confidence` (+ interval). Missing any → fails the validation gate.
4. **No number enters the graph without a `Source`.**
5. **Reconcile, don't overwrite; detect conflicts, don't silently average.**
6. LLM/API keys server-side only.
7. `confidence` (verified/derived/estimated) + interval + `freshness` preserved end-to-end and shown in the UI.

---

## 2. Repo layout (monorepo)
```
/apps
  /studio          # Admin back-office (Next.js)
  /terminal        # User front-end (Next.js + R3F) — 3D canvas
/services
  /engine          # FastAPI + LangGraph — Gemini routing + CVE + graph store + publish
    /cve           #   S0–S7: ingest→extract→resolve→derive→reconcile→score→gap
    /blueprint     #   theme analysis + iterative refinement + discovery
    /tickets       #   generation + state machine + unresolved-state persistence
    /calendar      #   per-company disclosure calendar
    /publish       #   assemble + validation gate + publish
  /pipeline        # feed ingestion, triggers, scheduler
/packages
  /graph-schema    # node/edge/claim type defs (single source of truth)
  /ui              # shared tokens / components (incl. confidence/freshness legend)
/infra             # docker-compose, db init, migrations
CLAUDE.md
ValueGraph_PRD_v5.md
ValueGraph_BUILD_PLAN.md
```
> If the layout drifts, update this section in the same PR.

---

## 3. Tech stack
| Layer | Choice | Notes |
|---|---|---|
| Graph DB | **Neo4j** | depth traversal + provenance (Cypher) |
| Vector DB | **Pinecone** (or pgvector) | entity resolution + claim dedup |
| RDBMS | **PostgreSQL** | users, tickets, jobs, billing, disclosure calendar |
| Cache/Queue | **Redis** | job queue, live-feed cache, rate limiting |
| Backend | **Python 3.11+, FastAPI, LangGraph** | CVE orchestration + Gemini routing |
| LLM | **Google Gemini only** | single provider |
| Frontend | **Next.js, React Three Fiber (Three.js)** | WebGL 60fps |
| Client state | **Zustand + TanStack Query** | canvas + server sync |

---

## 4. Cross-Verification Engine (CVE / VSCA) — get this right (PRD §6, BUILD_PLAN M3)
**One trade, two ledgers.** Trade A→C is the same dollar amount two ways:
- supplier view: `trade_value = supplier_rev_share × Revenue_A`
- customer view: `trade_value = customer_cost_share × CostBucket_C`

One disclosure yields `trade_value`; both let you cross-check. Worked shape: INTC discloses 21% of revenue from HPQ → `trade_value = 0.21 × Rev_INTC` → `≈ 9.5%` of HPQ COGS.

**Three constraints to implement:** (1) 10% disclosure ⇒ undisclosed customer < 10% (hard upper bound); (2) conservation (Σ shares per node ≤ 100% + undisclosed remainder); (3) cost-bucket typing (COGS/CAPEX/R&D/SG&A).

**Pipeline S0–S7:** ingest → extract claims (with **verbatim span**) → resolve entities → derive complementary side → **reconcile** (cluster, propagate constraints, **flag conflicts not average**, output point + interval) → estimate gaps (VSCA-est, always `estimated` + wide interval + auto-ticket) → score (tier + interval + freshness + next-update) → gap-detect → tickets.

**Confidence tiers:** `verified` (primary disclosure corroborated by ≥2 independent sources, or exact math from a primary filing) · `derived` (single disclosure + math) · `estimated` (algorithmic only). **Always ship an interval, never a bare point.** "Dual-verification" = Pro re-checks Flash extraction + multi-source corroboration (not two providers).

**Freshness (keep layers separate):** real-time (`price`/`market_cap` → node size) vs periodic (relationships → only as fresh as last filing). `freshness` ∈ {`fresh` <30d, `aging`, `stale` past next-expected-filing, `gap`}. Always show it.

**Disclosure Calendar:** per-company filing schedule → drives `next_expected_update` and scheduled CVE re-runs.

---

## 5. Frontend conventions (Terminal — viz IS the product)
- **60fps with hundreds of nodes + particle flows.** **Never render graph nodes as DOM** — WebGL via R3F, **instanced meshes**, particle pools; toggle *visibility* on depth/filter change, don't re-mount. LOD + frustum culling beyond ~1k nodes. Node size = live market cap (lerp, don't snap).
- **Encode data quality visually (signature feature):** edge style solid/dashed/ghost = confidence; freshness dot green/amber/red (`stale` → "update expected" badge); **gaps drawn as ghost "?" edges** (never omitted); always show a legend.
- **Per-figure provenance card:** value + interval, confidence chip, "as of … · N days old · next: …", source link. (Reserve an "Improve this" hook, disabled in v1 → Phase 2.)
- **Right panel = Live Context Feed:** raw news/interviews/filings, entity-linked, node-select filters it. **No score, no momentum, no forecast.**
- Real-time (price/mktcap) vs periodic (relationships) visually distinct in the drawer.
- **No `localStorage`/`sessionStorage`** in artifact-style previews; in-memory state only.
- Read `/mnt/skills/public/frontend-design/SKILL.md` before UI work.

---

## 6. Data & compliance guardrails
- **"Not investment advice"** disclaimer stays. We are not lawyers — flag scraping/redistribution, market-data licensing, and (Phase-2) community-liability questions to a professional; don't invent legal conclusions.
- **Don't redistribute filing/report full text** — store extracted numbers + source link, minimal quoting. Respect source ToS/robots.
- Live price/market cap needs a **licensed feed**; default to delayed until confirmed.
- Billing/PII isolated in Postgres; payments via a PG provider.

---

## 7. Commands
> Keep current as the repo materializes.
```bash
pnpm install                        # JS workspaces
uv sync                             # or: pip install -e services/engine

pnpm --filter terminal dev
pnpm --filter studio dev
uvicorn services.engine.main:app --reload

docker compose -f infra/docker-compose.yml up -d   # neo4j, postgres, redis

pnpm lint && pnpm typecheck
ruff check services && mypy services
pnpm test ; pytest services
```

---

## 8. Environment variables (Gemini only)
Never commit secrets. Document new keys here.
```
GOOGLE_API_KEY=
NEO4J_URI= / NEO4J_USER= / NEO4J_PASSWORD=
DATABASE_URL=            # Postgres
REDIS_URL=
PINECONE_API_KEY=
MARKET_DATA_API_KEY=     # licensed price/market-cap feed
# model ids (overridable)
MODEL_DEEP=gemini-3.1-pro-preview
MODEL_MEDIUM=gemini-3.5-flash
MODEL_LOW=gemini-3.1-flash-lite
```

---

## 9. Working style for Claude Code
- **Pull the next task from `ValueGraph_BUILD_PLAN.md`; read the referenced PRD sections.** Match terminology exactly (Studio/Terminal, Staging/Production, CVE/VSCA, Claim, ticket, blueprint, confidence/freshness, Disclosure Calendar, Live Context Feed).
- One task per PR; satisfy every acceptance criterion + the global Definition of Done before "done."
- Respect the suggested PR sequence / critical path (M0→M1→M2→M3→M4; M5/M6 after a sample publish; M7 on M3+M6).
- Touch the schema only in `packages/graph-schema` and propagate — don't fork type defs.
- Prefer iterative refinement over rewrites; preserve working code.
- Verify Gemini model IDs / SDK details against current Google docs, not memory.

**Do:** keep Two-Track separation airtight · tag every number (source+as_of+next_update+confidence+interval) · reconcile not overwrite, flag conflicts not average · draw gaps, show freshness · route all model calls through the router.

**Don't:** build any prediction/forecasting (v1) · build the community layer (v1) · expose Staging/intermediates to users · auto-publish · put API keys client-side · render the graph with DOM nodes · use any non-Gemini model.

---

## 10. Glossary
| Term | Meaning |
|---|---|
| Node | a listed company (size = live market cap) |
| Edge (`SUPPLIES`) | a supplier→customer trade (the core v1 relationship) |
| Blueprint | the LLM-analyzed, iteratively-refined plan of what's needed to build a theme's chain |
| CVE / VSCA | Cross-Verification Engine / ValueGraph Supply Chain Algorithm (derive + reconcile + estimate) |
| Claim | one atomic, sourced assertion extracted from a document (with verbatim span) |
| two ledgers | deriving/cross-checking a trade from supplier-side and customer-side disclosures |
| conservation / 10% rule | constraints that bound under-determined edges |
| confidence | verified / derived / estimated (+ interval) |
| freshness | fresh / aging / stale / gap |
| Disclosure Calendar | per-company filing schedule → next-update + scheduled re-runs |
| Live Context Feed | right-panel raw news/interview/filing stream (context only, no forecast) |
| ticket | structured request to fill/verify a gap; unresolved states persist & feed CVE |
| Staging / Production | mutable work DB / published read-only DB |
| Publish | admin-approved Staging→Production sync |

> Docs are English; the consumer Terminal UI will likely be Korean-localized — keep user-visible strings in an i18n layer, not hardcoded.
