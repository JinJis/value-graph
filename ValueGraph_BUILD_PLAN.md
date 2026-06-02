# 🛠️ ValueGraph — Build Plan (Milestones & Tasks)

> Execution companion to `ValueGraph_PRD_v5.md`. This is the **task source of truth** for Claude Code.
> **Rules:** build **one milestone at a time**, **one task per PR**, and **do not mark a task done until every acceptance criterion (AC) passes.** Don't skip ahead or invent scope. When a task says "see PRD §X", read it.
> **Tag format:** `[M{n}-{AREA}-{nn}]` (e.g. `[M1-BLU-02]`). Reference the tag in branch names, commits, and PR titles.
> **Models:** Gemini only (DEEP=`gemini-3.1-pro-preview`, MEDIUM=`gemini-3.5-flash`, LOW=`gemini-3.1-flash-lite`, RESEARCH=Gemini Deep Research Agent). All via the central router; IDs from env.

---

## Legend
- **Depends** — task tags that must be done first.
- **Files** — where the work primarily lives (create if absent).
- **AC** — acceptance criteria; all must pass.
- 🔴 = on the critical path.

## Global "Definition of Done" (applies to every task)
1. Acceptance criteria all pass.
2. `pnpm lint && pnpm typecheck` and `ruff check services && mypy services` clean for touched code.
3. Tests added/updated and green (`pnpm test`, `pytest services`).
4. No secrets committed; no API keys client-side.
5. No invariant from PRD §4 violated (Terminal reads Production only; no auto-publish; every figure has source+as_of+next_update+confidence+interval; no number without a Source).

---

# M0 — Scaffolding & infrastructure
**Goal:** an empty but runnable monorepo with DBs, schema package, and a working Gemini router.

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M0-REPO-01]` | Monorepo init: pnpm workspaces + uv; folder tree per CLAUDE.md §2 | — | root, `pnpm-workspace.yaml`, `pyproject.toml` | `pnpm install` & `uv sync` succeed; `apps/*` & `services/*` exist and boot to a stub |
| 🔴 `[M0-INFRA-02]` | docker-compose: Neo4j + Postgres + Redis with healthchecks | M0-REPO-01 | `infra/docker-compose.yml` | `docker compose up -d` → all 3 healthy; a connection smoke-test script passes for each |
| 🔴 `[M0-SCHEMA-03]` | `graph-schema` package: Theme/Company/Division/Product/Source/Claim nodes + HAS_DIVISION/PRODUCES/SUPPLIES/SUPPORTS/SOURCED_FROM edges (per PRD §5). One canonical definition, consumed by TS (apps) and Python (services) | M0-REPO-01 | `packages/graph-schema/**` | Types import from both an app and a service; a schema-validation unit test passes; required fields on `SUPPLIES` enforced (PRD §5.3) |
| 🔴 `[M0-LLM-04]` | Gemini client + central router with tiers DEEP/MEDIUM/LOW/RESEARCH → model IDs from env | M0-REPO-01 | `services/engine/llm/router.py`, `.env.example` | One call per tier returns text; IDs read from env (no hardcode); a bad tier raises; keys never logged |
| `[M0-API-05]` | FastAPI engine skeleton + Next.js studio & terminal skeletons; `/health` on each | M0-REPO-01 | `services/engine/main.py`, `apps/studio`, `apps/terminal` | All three serve `/health` locally |
| `[M0-DB-06]` | Postgres migrations (users, themes-meta, tickets, jobs, disclosure_calendar) + Neo4j constraints (unique `ticker`) | M0-INFRA-02, M0-SCHEMA-03 | `infra/migrations/**`, `services/engine/db/**` | Migrations run idempotently; unique-ticker constraint enforced |

**Milestone DoD:** `docker compose up` + `pnpm dev` + engine boot all green; schema importable; a smoke call hits each Gemini tier.

---

# M1 — Theme creation + blueprint analysis (Admin steps 1–2)
**Goal:** an admin creates a theme; Gemini analyzes it into a structured, iteratively-refined blueprint of what's needed to build the chain. (PRD §8.1–8.2)

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M1-THEME-01]` | Theme CRUD API + Studio "New Theme" screen with Additional-Context upload (PDF / seed tickers / reports) | M0-* | `services/engine/themes/**`, `apps/studio/themes/**` | Create/list/open themes; uploaded context stored in object storage **and** as `Source` records; files re-openable |
| 🔴 `[M1-BLU-02]` | **Blueprint generation (DEEP)** — Gemini analyzes theme+context → structured blueprint: candidate companies (global, with country/exchange), products/roles, relationship types to populate, and **required data points per company** | M1-THEME-01, M0-LLM-04 | `services/engine/blueprint/**` | For "AI Data Centers" returns ≥30 companies spanning ≥4 of KR/US/JP/CN/TW; output validates against a blueprint JSON schema; persisted to Staging |
| 🔴 `[M1-BLU-03]` | **Iterative refinement (2–3 rounds)** — re-feed blueprint to DEEP to expand hidden vendors, dedupe, fill gaps; stop at convergence or 3-round cap | M1-BLU-02 | `services/engine/blueprint/refine.py` | Each round persisted with a version; companies de-duplicated (no two nodes for same ticker/alias); loop stops at ≤3 rounds or when round-delta < threshold; round log stored |
| `[M1-DISC-04]` | **RESEARCH discovery pass** (Gemini Deep Research) to broaden constituents; merge into blueprint with source attribution | M1-BLU-02 | `services/engine/blueprint/discover.py` | Discovered companies merged + entity-resolved against existing; each carries a `Source`; duplicates avoided |
| `[M1-REV-05]` | Studio **Blueprint review** screen — editable company/product/relationship tree; admin approves to advance | M1-BLU-03 | `apps/studio/blueprint/**` | Blueprint renders as editable tree/table; edits persist; "Approve" advances to ticketing (M2) |

**Milestone DoD:** creating "AI Data Centers" yields a versioned, de-duplicated, multi-country blueprint with required-data-points, reviewable and approvable in Studio.

---

# M2 — Ticket generation + admin processing (Admin steps 3 & 6)
**Goal:** turn blueprint gaps into tickets, let the admin resolve them by uploading evidence, and persist unresolved states as reusable data. (PRD §8.3, §8.6)

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M2-GEN-01]` | **Gap→ticket generator** — every required-but-unsourced data point in the approved blueprint → exactly one structured ticket (metric, target company/edge, reason, current estimate if any) | M1-REV-05 | `services/engine/tickets/generate.py` | Each unsourced data point yields one OPEN ticket; no duplicate tickets for the same target; tickets persisted in Postgres |
| 🔴 `[M2-QUEUE-02]` | Studio **ticket queue** UI (filter by company/metric/status, priority sort) | M2-GEN-01 | `apps/studio/tickets/**` | List/sort/open tickets; ticket shows exactly what's requested and why |
| 🔴 `[M2-PROC-03]` | **Ticket processing — evidence upload** (PDF/image/text/URL) → stored as `Source` (type, publisher, as_of_date, url, language); status → SUBMITTED | M2-QUEUE-02 | `apps/studio/tickets/upload`, `services/engine/sources/**` | Upload creates a `Source` linked to the ticket; as-of date captured; status transitions to SUBMITTED; file re-openable |
| 🔴 `[M2-UNRES-04]` | **Unresolvable/deferred handling** — mark ticket UNRESOLVABLE/DEFERRED with reason code (not-found / not-disclosed / paywalled / ambiguous); **persisted & reusable by CVE** (e.g. "not-disclosed" → sets edge 10% upper bound) | M2-QUEUE-02, M0-SCHEMA-03 | `services/engine/tickets/state.py` | Status + reason persisted; CVE can query unresolvable tickets; a "not-disclosed" mark records the ≤10% upper bound on the target edge and the reason carries into future builds |
| `[M2-SM-05]` | Ticket **state machine + audit log** (who/what/when) | M2-GEN-01 | `services/engine/tickets/state.py` | Invalid transitions rejected; full history queryable per ticket |

**Milestone DoD:** approved blueprint → tickets; admin can upload evidence to close a ticket or mark it unresolvable with a reason; all states persist and are queryable by CVE.

---

# M3 — Cross-Verification Engine / VSCA (Admin step 4) 🔴 critical path
**Goal:** quantify and reconcile edges from sources, with confidence + freshness, and emit new gap tickets. (PRD §6)
> Each S-stage is its own task. Build with unit tests using small fixture filings.

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M3-EXT-01]` | **S1 Claim extraction (MEDIUM)** — from a `Source`, extract atomic typed claims (supplier-side / customer-side / absolute / qualitative) each with **verbatim text span** | M2-PROC-03 | `services/engine/cve/extract.py` | On a fixture 10-K excerpt, extracts share claims with the exact span; **no span → no claim**; output validates against `Claim` schema; qualitative (no-number) claims recorded too |
| 🔴 `[M3-ENT-02]` | **S2 Entity resolution** — map mentions → canonical `Company` via dictionary + embedding (Vector DB) + LLM adjudication; below threshold → resolution ticket | M3-EXT-01, M0-INFRA-02 | `services/engine/cve/resolve.py` | Known aliases/subsidiaries/multilingual names resolve to the right ticker; ambiguous cases create a ticket (no silent guess); test set ≥90% precision on fixtures |
| 🔴 `[M3-DER-03]` | **S3 Derivation (VSCA math)** — compute complementary ledger side; assign cost bucket | M3-ENT-02 | `services/engine/cve/derive.py` | Unit test reproduces INTC 21%-of-revenue-from-HPQ → `trade_value` and **≈9.5% of HPQ COGS**; `cost_bucket` assigned per typing rules |
| 🔴 `[M3-REC-04]` | **S4 Reconciliation** — cluster multiple estimates/edge; apply conservation + 10% bounds; **detect conflicts (flag + ticket, never average)**; output point + interval | M3-DER-03 | `services/engine/cve/reconcile.py` | Conflicting independent claims → edge flagged `conflict` + ticket (not averaged); a conservation violation down-scales or flags; **every edge value has an interval, never a bare point** |
| 🔴 `[M3-EST-05]` | **S5 VSCA-est (DEEP)** — estimate suspected-but-unquantified edges via peer analogy / capacity / priors; always `estimated` + wide interval + auto-ticket | M3-REC-04, M0-LLM-04 | `services/engine/cve/estimate.py` | A qualitative-only relationship yields an `estimated` edge with a wide interval and an auto-generated ticket; never tagged higher than `estimated` |
| 🔴 `[M3-SCORE-06]` | **S6 Scoring** — confidence tier (verified/derived/estimated) + interval + freshness + `next_expected_update` | M3-REC-04 | `services/engine/cve/score.py` | Tier rules per PRD §6.2 (≥2 independent sources → `verified`); freshness computed from as_of vs next-expected; values carry `next_expected_update` |
| 🔴 `[M3-GAP-07]` | **S7 Gap detection** — emit tickets for estimated / conflict / stale / unclosed-conservation | M3-SCORE-06, M2-GEN-01 | `services/engine/cve/gaps.py` | Each gap type produces a ticket; after uploading resolving evidence and re-running, the edge upgrades and the ticket closes |
| 🔴 `[M3-ORCH-08]` | **CVE orchestration (LangGraph)** — wire S0–S7 into a re-runnable pipeline; triggers: admin run / new evidence / scheduled (M7) | M3-EXT-01…M3-GAP-07 | `services/engine/cve/pipeline.py` | Full pipeline runs end-to-end on a theme; **idempotent** (re-run yields same state given same inputs); all intermediates persisted |

**Milestone DoD:** upload a fixture filing → CVE extracts, resolves, derives, reconciles, scores, and either quantifies an edge with confidence+interval+freshness or emits a gap ticket; re-running after more evidence upgrades edges.

---

# M4 — Persistence, graph assembly, publish (Admin steps 5 & 7)
**Goal:** persist everything, assemble the publishable graph, gate it, and publish to Production. (PRD §8.5, §8.7)

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M4-PERSIST-01]` | Persist all CVE artifacts (Neo4j nodes/edges/claims/sources + Postgres tickets/jobs), **versioned per theme build** | M3-ORCH-08 | `services/engine/db/**` | A theme's full state is reconstructable from the DB; **nothing lives only in memory**; build versions retrievable |
| 🔴 `[M4-ASM-02]` | **Graph assembly** — once completeness ≥ threshold (or admin override), assemble the publishable supply-chain graph | M4-PERSIST-01 | `services/engine/publish/assemble.py` | Assembled graph contains only edges meeting schema rules; completeness threshold configurable; override logged |
| 🔴 `[M4-GATE-03]` | **Validation gate** — block publish unless every exposed figure has source + as_of + next_update + confidence + interval | M4-ASM-02 | `services/engine/publish/gate.py` | Gate report lists each violation; publish disabled until clean or an explicit, logged admin override |
| 🔴 `[M4-PUB-04]` | **Publish** — sync Staging → Production (read-only, versioned snapshot) | M4-GATE-03 | `services/engine/publish/publish.py` | Production reflects the published version; Terminal reads it; later Staging edits don't leak to Production until next publish |
| `[M4-DQ-05]` | Theme **data-quality meter** (verified/derived/estimated/gap %) | M4-PERSIST-01 | `services/engine/publish/quality.py`, `apps/studio` | Computed from the graph; shown in Studio (and read-only in Terminal) |

**Milestone DoD:** a seeded theme passes the gate and publishes; Production is a clean read-only snapshot; data-quality meter reflects reality.

---

# M5 — Terminal macro map (User steps 1–2 basics)
**Goal:** the 3D supply-chain canvas with flow, depth, and the confidence/freshness encoding. (PRD §9.1–9.2, §10)
> Read `/mnt/skills/public/frontend-design/SKILL.md` before UI work. Performance is an AC, not a nicety.

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M5-CANVAS-01]` | WebGL canvas (R3F) rendering Production nodes; **instanced meshes**; node size = live (or delayed/mock) market cap | M4-PUB-04 | `apps/terminal/canvas/**` | Hundreds of nodes at **60fps**; size binds to the market feed; **no DOM nodes** |
| 🔴 `[M5-FLOW-02]` | **SUPPLIES edges with directional particle flow**; thickness = trade value; particle pooling | M5-CANVAS-01 | `apps/terminal/canvas/edges.ts` | Particles flow supplier→customer; thickness scales with value; 60fps maintained |
| 🔴 `[M5-DEPTH-03]` | **Depth slider (1..N)** toggling node/edge **visibility** (not re-mount); LOD + frustum culling beyond ~1k nodes | M5-FLOW-02 | `apps/terminal/canvas/depth.ts` | Depth change updates visibility < 100ms; no re-mount; culling active beyond ~1k nodes |
| 🔴 `[M5-ENCODE-04]` | **Confidence/freshness encoding** — edge style solid/dashed/ghost (verified/derived/estimated) + freshness dot green/amber/red + **gaps drawn as ghost "?" edges**; legend | M5-FLOW-02 | `apps/terminal/canvas/encoding.ts` | Encoding matches PRD §6.4/§9; gaps visible (not omitted); a legend explains it |
| `[M5-NAV-05]` | Camera/interaction (pan/zoom/select) + dark theme | M5-CANVAS-01 | `apps/terminal/canvas/controls.ts` | Smooth navigation; selecting a node highlights its edges |

**Milestone DoD:** a published theme renders as an explorable 3D map at 60fps with flow, depth control, and visible confidence/freshness/gaps.

---

# M6 — Terminal drilldown, evidence, live feed (User steps 2 & 4)
**Goal:** rich evidence on click + the right-panel Live Context Feed. (PRD §9.2, §9.4)

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M6-DRAWER-01]` | **Company Drawer** — division tree → products → who-buys-each (+share); **live price/mktcap shown separately** from periodic figures | M5-ENCODE-04 | `apps/terminal/drawer/**` | Clicking a node opens the drawer; clicking a product highlights its customer edges on canvas; real-time vs periodic visually distinct |
| 🔴 `[M6-PROV-02]` | **Per-figure provenance card** — value + interval, confidence chip, "as of … · N days old · next: …", **source link** to the document; reserve an "Improve this" hook (disabled in v1) | M6-DRAWER-01 | `apps/terminal/provenance/**` | Every figure exposes full provenance; source link opens the actual document; next-update shown |
| 🔴 `[M6-EDGE-03]` | **Edge inspector** — supporting claims, both-ledger shares, reconciliation summary (+ conflict if flagged) | M6-DRAWER-01 | `apps/terminal/edge/**` | Shows all `SUPPORTS` claims + sources; conflict state visible when flagged |
| 🔴 `[M6-FEED-04]` | **Right-panel Live Context Feed** — stream of news / CEO interviews / filings, entity-linked to nodes; selecting a node filters the feed; item → source. **Context only: no score, no momentum, no forecast** | M5-CANVAS-01, M3-EXT-01 | `apps/terminal/feed/**`, `services/pipeline/feed/**` | Feed updates as items ingest; items entity-linked; node-select filters feed to that node; **no predictive UI**; clicking shows source |

**Milestone DoD:** clicking nodes/edges/products surfaces full, sourced evidence with freshness + next-update; a live, node-linked context feed runs in the right panel with zero forecasting.

---

# M7 — Disclosure calendar & scheduled refresh (User step 3 + freshness intelligence)
**Goal:** track when each company next discloses; surface it; re-run CVE on new filings. (PRD §6.6, §9.3)

| Tag | Task | Depends | Files | AC |
|---|---|---|---|---|
| 🔴 `[M7-CAL-01]` | **Disclosure-calendar model** — per-company fiscal calendar + expected filing dates (10-K/10-Q, 사업보고서/분기보고서, EDINET, earnings), learned from history + sources | M4-PERSIST-01 | `services/engine/calendar/**` | Each company has `next_filing_estimate` dates; backed by Postgres `disclosure_calendar`; powers `next_expected_update` on figures |
| 🔴 `[M7-NEXT-02]` | **"Next update" surfacing in Terminal** — per-figure next-refresh + theme-level upcoming-update timeline | M7-CAL-01, M6-PROV-02 | `apps/terminal/timeline/**` | Each figure/edge shows when its data is expected to refresh; items past expected date flagged `stale` |
| 🔴 `[M7-TRIG-03]` | **New-filing trigger → targeted CVE re-run** — on detecting a new relevant filing for a tracked company, enqueue re-ingest + CVE for affected edges | M7-CAL-01, M3-ORCH-08 | `services/pipeline/triggers/**` | A detected new filing creates an ingestion + CVE job scoped to that company; upgraded data re-enters Staging (admin re-publishes) |
| `[M7-SCHED-04]` | **Scheduler** — periodic checks for due filings + feed refresh; backoff/retry; observable in Studio | M7-TRIG-03 | `services/pipeline/scheduler/**` | Jobs run on schedule with retry/backoff; job status visible in Studio |

**Milestone DoD:** every figure shows when it'll next update; when a new filing is detected, CVE re-runs for that company and the admin can re-publish a fresher map.

---

# Phase 2 — Community contribution (not started in v1)
**Open only after the flagship theme is complete admin-only.** Refer to PRD §7. Tasks (to be detailed later): contributor submission flow (source required) · **source-check** (model re-verifies the URL contains the claimed value) · reputation system · reviewer tooling + two-reviewer rule for high-impact edges · anti-abuse (dupes/spam/COI) · accepted-evidence → CVE re-run. **v1 requirement:** keep the ticket/Source/Claim model and review/publish seam clean so this plugs in without rework.

---

## Suggested PR sequence (critical path)
`M0-REPO-01 → M0-INFRA-02 → M0-SCHEMA-03 → M0-LLM-04 → M0-API-05 → M0-DB-06`
`→ M1-THEME-01 → M1-BLU-02 → M1-BLU-03 → (M1-DISC-04) → M1-REV-05`
`→ M2-GEN-01 → M2-QUEUE-02 → M2-PROC-03 → M2-UNRES-04 → M2-SM-05`
`→ M3-EXT-01 → M3-ENT-02 → M3-DER-03 → M3-REC-04 → M3-EST-05 → M3-SCORE-06 → M3-GAP-07 → M3-ORCH-08`
`→ M4-PERSIST-01 → M4-ASM-02 → M4-GATE-03 → M4-PUB-04 → (M4-DQ-05)`
`→ M5-CANVAS-01 → M5-FLOW-02 → M5-DEPTH-03 → M5-ENCODE-04 → (M5-NAV-05)`
`→ M6-DRAWER-01 → M6-PROV-02 → M6-EDGE-03 → M6-FEED-04`
`→ M7-CAL-01 → M7-NEXT-02 → M7-TRIG-03 → (M7-SCHED-04)`

*(Items in parentheses can be deferred slightly without blocking the next milestone. M5/M6 frontend can be developed in parallel against a published sample theme once M4-PUB-04 lands.)*
