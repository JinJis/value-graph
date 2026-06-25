# Backend Refactoring Plan (RF-01 … RF-18)

> **Goal:** reduce structural debt in the backend services **without changing behavior**.
> Pure structure/maintainability work — every task ships with the touched service's unit tests
> green + the relevant e2e/coverage harness still passing (Definition of Done, CLAUDE.md §5).
>
> **Process:** one task per PR/commit; **tag the `RF-id`** in the branch/commit/PR. Pull tasks in
> phase order (0 → 1 → 2 → 3). Update the **Status** column in the same change. This doc is the
> task source for the backend refactor — derived from a 6-service parallel audit (2026-06-25).

## Guardrails — refactors must PRESERVE these invariants (CLAUDE.md §2)

A refactor that touches any of these must keep the behavior identical:

- **Manifest/catalog is the single source of truth** — REST docs, MCP tools, RAG registration,
  entitlement, metering, agent tool list, builder categories all derive from it. Every Resource
  carries `category` + `cadence` (load fails if missing). Don't fork it.
- **Gateway is the only path to data** (auth → entitlement → rate-limit → meter/audit). Don't bypass
  or split the enforcement point. Entitlement = activation.
- **Keys server-side only.** **Gemini-only, one router** — no other provider, no forked tenancy.
- **No keyword/heuristic/if-ladder judgment** — routing, clarification, decomposition, difficulty,
  guardrail intent are LLM-judged. A refactor must not (re)introduce keyword logic.
- **No number without a source** (`source`+`as_of`+`freshness`+`cadence`); unbuilt → 501, never fabricate.
- **No forecasting/advice** (refused at the agent boundary, label shown). Alerts/briefs stay facts-only.
- **Search stays fail-safe** (a reranker/store failure falls back, never 500s the user).

## Status legend

`TODO` · `WIP` · `DONE` · `BLOCKED` · `DROPPED`. Severity = maintainability impact. Effort:
S(<1h) · M(half-day) · L(multi-day).

---

## Phase 0 — Quick wins (safe, small, do first)

| ID | Task | Service | Sev | Eff | Status |
|---|---|---|---|---|---|
| **RF-01** | Dead-code + config-bug sweep. **DONE:** removed duplicate KIS keys in `config.py`; deleted ~90 LOC of legacy keyword-routing dead code from agent-engine `routing.py` (kept only the live `resolve_ticker`/`_user_text`). **Verified NOT dead (kept):** `opendart.as_reported()` (KR route `financials.py:108` calls it — honest empty per invariant #6), `store/ingest.py` `_STATEMENTS`/`_SKIP` (used by `ingest_ticker`/KR bulk), `jobs.py` type hints (already present), `evidence.py` (already documented). | datasets, agent-engine | high | S | DONE |
| **RF-02** | Shared provider number-parsing: new `providers/_parse_utils.py` (`parse_int`/`parse_float`, comma-aware) replacing `_num` (sec_edgar + fmp), `_i`/`_f` (kis) via import-alias (zero call-site churn). | datasets | high | S | DONE |
| **RF-03** | Single provenance field tuple: collapsed `_PROV` (`store.py`) + `_PROVENANCE` (`models.py`) into one shared `models.PROVENANCE_FIELDS`. | rag | med | S | DONE |

## Phase 1 — Cross-cutting foundations (highest value; other refactors build on these)

| ID | Task | Service | Sev | Eff | Status |
|---|---|---|---|---|---|
| **RF-04** | Router toolkit `routers/_common.py` (`validate_interval`/`validate_period` + `INTERVALS`/`PERIODS`, `gather_best_effort`, `tickers_response`). Migrated 8 routers (prices, technical, financials, metrics, gurus, company, filings, earnings) — removed the duplicated `_INTERVALS`/`_PERIODS`/`_check_period`, the `_one`+gather+filter pattern (×3), and the `list_tickers→TickersResponse` one-liners (×5). Verified live: identical 400 messages + responses. | datasets | high | M | DONE |
| **RF-05** | `JobRunner` context manager in `store/jobs.py` (start→progress→finish, error→status); refactor prices/news/filing ingest onto it. Split `prices_ingest.py` into prices + `corp_actions_ingest.py` + shared helpers. | datasets | high | M | TODO |
| **RF-06** | Upstream adapter: generic `CachedLoader(key, ttl, loader)` (TTL+lock) for SEC ticker index / OpenDART corp map / KIS token; standardize upstream error/timeout handling on `app.errors`. | datasets | high | M | TODO |
| **RF-07** | Catalog single-source: fold the hand-maintained `_CATEGORY`/`_CADENCE` maps into the Resource/policy definitions (keep the load-time "every tool categorized/cadenced" assertion); dedupe `_apply_categories`/`_apply_cadence` into one helper. | datasets | med | M | TODO |

## Phase 2 — God-file structural splits

| ID | Task | Service | Sev | Eff | Status |
|---|---|---|---|---|---|
| **RF-08** | `artifacts.py` (598): replace the 15-branch `if name.endswith(...)` ladder with a `tool → handler` registry/dispatch; extract `enrich_artifacts()` (markers/overlays/annotations in one call). | agent-engine | high | M | TODO |
| **RF-09** | Split `agent.py` (809): extract `intake.py` (task analysis + guardrail) and `enrichment.py` (followups/evidence) from the orchestration loop; consolidate prompts/schemas into `prompts.py`; dedupe chat↔agent citation/artifact assembly into `results.py`. | agent-engine | high | L | TODO |
| **RF-10** | `chat.py` (436): extract an SSE event-builder from the loop; wrap Gemini calls in one bounded helper (consistent timeout/error isolation). | agent-engine | med | M | TODO |
| **RF-11** | CRUD/ownership DRY: `_check_ownership(db, model, id, email)` + a shared list/get/create/update/delete base across agents/prompts/board/watchlists; `to_dict`/`safe_json_list`/`JsonColumn` helpers for the repeated `_out`/`json.loads(... or "[]")` patterns. | studio-api | high | M | TODO |
| **RF-12** | Split `alerts.py` (565) into render/model (pure `render_message`/`fire_alert`/`compute_next_fire`) + scheduler glue + routes; move trigger metadata + fallback templates into one `TRIGGERS` table. | studio-api | high | L | TODO |
| **RF-13** | Extract `idempotent_clone()` (community + source_id + idempotent) from `prompts.import_prompt` into a reusable module, ready for agents/analysts cloning. | studio-api | med | M | TODO |
| **RF-14** | Split `admin/main.py` (986) into per-section `APIRouter` modules + a `state.py` (DB_STATUS/ENGINES/TABLES) + a `ServiceClient` wrapping the repeated `_safe_get`/`httpx.AsyncClient` fetches. | admin | high | M | TODO |
| **RF-15** | Admin HTML component lib in `views.py` (card/tile/table/status-row builders) + shared status/badge constant maps (4 inline dicts → 1). Jinja2 adoption is a **separate** decision, not in scope here. | admin | med | M | TODO |

## Phase 3 — Gateway / RAG hardening + test gaps

| ID | Task | Service | Sev | Eff | Status |
|---|---|---|---|---|---|
| **RF-16** | Gateway pipeline: extract an `EntitlementResolver` + make the auth→entitle→ratelimit→meter→audit chain explicit/composable; `AuditAction` enum; TTL-based rate-limit bucket cleanup; validate `Activation.byo_credentials` JSON at upsert. | control-plane | med | M | TODO |
| **RF-17** | RAG backend registry: unify `get_embedder`/`get_reranker`/`get_store` with startup config validation + a lifespan shutdown hook; a shared filter-matcher so MemoryStore/PgVectorStore have identical filter/tenant semantics; structured reranker-failure logging. | rag | med | M | TODO |
| **RF-18** | Test gaps: ingest job lifecycle (`start_job`/progress/`finish_job`); RAG tenant isolation + reranker-fallback + Memory↔Pg store parity; gateway rate-limit key isolation + minute-boundary; MCP "tool list derives from catalog" assertion. | all | med | L | TODO |

---

## Deferred / rejected (value vs. risk)

- **asyncpg migration** (async DB everywhere) — behavior-risky, large scope; not a pure refactor.
- **hypothesis property/fuzz tests** — net-new test infra, not refactoring.
- **Jinja2 for the admin panel** — medium value, real effort; revisit after RF-14/15 land.

## Per-task Definition of Done

Touched service's unit tests added/updated and green · the relevant `scripts/e2e*.sh`/`coverage.sh`
still passing · no behavior change (same responses/contracts) · docs updated if a structure moved ·
this file's **Status** flipped to `DONE` in the same commit, tagged with the `RF-id`.
