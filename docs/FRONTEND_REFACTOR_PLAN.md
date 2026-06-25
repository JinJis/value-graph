# Frontend Refactoring Plan (FE-01 … FE-14)

> **Goal:** reduce structural debt in the `web/` Next.js (App Router) frontend **without changing
> behavior or UI**. Pure structure/maintainability work.
>
> **⚠️ No test suite.** The frontend has no test runner (devDeps are `typescript` + `@types/*` only).
> So each task's verification is **`npx tsc --noEmit` clean + `next build` succeeds + a live smoke**
> of the affected surface — not unit tests. Adding a runner (vitest + testing-library) is **FE-14**,
> optional/foundational. Refactor carefully: there is no safety net beyond the type-checker + build.
>
> **Process:** one task per PR/commit; **tag the `FE-id`**. Pull tasks in phase order (0→1→2→3).
> Update the **Status** column in the same change. Derived from a 5-area parallel audit (2026-06-25).

## Guardrails — refactors must PRESERVE these (CLAUDE.md §4 + UI invariants)

- **Read `/mnt/skills/public/frontend-design/SKILL.md` before any visual change.** This effort is
  structure-only: **no UI/visual/behavior change** (same DOM output, same styles, same interactions).
- **Browser holds only an Auth.js session.** Keys/tenant-key stay server-side; the BFF (`/api/*`)
  re-derives identity from the session and proxies to studio-api with the service token + user email.
  Never trust a client-supplied user id.
- **No `localStorage`/`sessionStorage`** in preview/artifact contexts.
- **Charts stay canvas** (`lightweight-charts`) — never render the graph with DOM nodes.
- **Provenance is never dropped** — every figure shows `source`+`as_of`+`freshness`+`cadence`.
- **Only `periodic` widgets (`cadence != one_shot`) carry a bell**; the alert trigger is **derived from
  cadence/category metadata, never a name-regex** (invariant #9). `lib/alerts.ts` already honors this.
- **Gemini-only** (the builder exposes no model choice); **no forecasting**; the **guardrail refusal
  label stays shown**; the builder groups tools by **catalog category**, selecting individual tools.

## Status legend

`TODO` · `WIP` · `DONE` · `BLOCKED` · `DROPPED`. Sev = maintainability impact. Effort: S/M/L.

---

## Phase 0 — Shared foundations (low-risk, high-leverage; do first)

| ID | Task | Sev | Eff | Status |
|---|---|---|---|---|
| **FE-01** | Created `lib/types.ts` as the single source: `Artifact` (+ chart child types), `Citation`, the chat/SSE types (`ToolUse`/`Think`/`Clarify`/`ClarifyOption`/`SubAgent`/`Msg`), and `WidgetSpec`. Moved the defs out of `ArtifactCard`/`SourceCard`/`Chat` (importing a *type* no longer drags in a *component*); the components **re-export** them for back-compat → zero importer churn. **`BoardCanvas`'s `spec: any` → `WidgetSpec` deferred to FE-10** (the union needs narrowing at every `spec.x` access — a cascade best done with the WidgetFrame split). tsc clean (1 known react-grid-layout baseline error) + `next build` passes + page renders. | high | M | DONE |
| **FE-02** | Created `lib/format.ts` (`currencyOf`/`fmtBig`/`fmtPrice`/`fmtVol`/`fmt`). **Audit overstated the duplication** — these weren't copied across files; they lived in `ArtifactCard` and `TradeChart` *imported `fmtBig` from it*, coupling a chart to a card module. Moved them to lib; `ArtifactCard` + `TradeChart` now import from `lib/format` (TradeChart fully decoupled from ArtifactCard — types→`lib/types`, format→`lib/format`). `BoardCanvas` doesn't use them. tsc clean + `next build` passes. | med | S | DONE |
| **FE-03** | Created `lib/widgets.ts` (`widgetKind(spec)` — the artifact/source/text classifier from `BoardCanvas.kindOf` — + coarse `widgetKindLabel`); migrated `BoardCanvas` and `PinPicker` onto it. **Removed the real duplicate:** `ui.tsx`'s `CADENCE_LABEL` (byte-identical to `lib/alerts`, its own comment admitted "mirrors") → `CadenceTag` now uses `cadenceLabel` from `lib/alerts` (no cycle — `lib/alerts` imports nothing). Left `WidgetGallery.kindLabel` alone (a *different* concept — the artifact's fine-grained display type 차트/표·값/내러티브). tsc clean + `next build` passes. | med | S | DONE |

## Phase 1 — Cross-cutting hooks + the BFF/modal primitives

| ID | Task | Sev | Eff | Status |
|---|---|---|---|---|
| **FE-04** | `lib/hooks.ts`: `useFetch<T>(url, deps?)`, `useAsyncOp()` (busy/error/run), `useDebounce(v, ms)` — each re-implemented across the modals (`PromptLibrary`/`Watchlists`/`AgentBuilder`/`AlertSheet`). Migrate them onto the hooks. | high | M | TODO |
| **FE-05** | BFF: extract `streamStudioEvents(req, path)` into `lib/studio.ts` for the SSE routes (`api/chat`, `api/runs/[id]/stream`) — the only 2 that bypass the existing `proxyStudio`/`studioFetch` helper (the ~38 JSON routes already use it — the audit's "40× copy-paste" was wrong). Standardize query-string forwarding + the `SSE_HEADERS` constant. | med | S | TODO |
| **FE-06** | Make `ui.tsx`'s `Modal` the single composable shell (title-as-node, footer slot) **with a11y** (focus trap + Escape + `role="dialog"`/`aria-modal`/`aria-labelledby`), and migrate `AlertSheet` + `WidgetGallery` off their inline `modal-backdrop` re-implementations. | med | M | TODO |

## Phase 2 — God-component splits

| ID | Task | Sev | Eff | Status |
|---|---|---|---|---|
| **FE-07** | `Chat.tsx` (797): extract `useChatStream` — the SSE reader + the `applyEvent` reducer + conversation tracking (replace the `viewConvRef`/`streamConvRef` dance with an `AbortController` per stream so fast conversation-switches can't orphan a reader). | high | L | TODO |
| **FE-08** | `Chat.tsx`: extract `<MessageList>` (memoized per-message sub-components so a `token` event doesn't re-render the whole list) + `<ChatComposer>` (input/@mention/ticker-fill state). Chat drops to a thin shell. | high | M | TODO |
| **FE-09** | `ArtifactCard.tsx` (458): replace the per-`kind` if-chain (candlestick/timeseries/table/kpi/narrative) with a `kind → renderer` registry (mirrors the backend RF-08 artifact handlers). Extract `ResponsiveTable` to its own file. | med | M | TODO |
| **FE-10** | `BoardCanvas.tsx` (394): extract `<WidgetFrame>` (the per-widget chrome: drag handle · freshness dot · cadence tag · bell-gate · refresh/delete) so BoardCanvas keeps only grid+DnD+pin-CRUD; memoize `toLayout(items)`; derive the spec fields once (not per render). | high | M | TODO |
| **FE-11** | `TradeChart.tsx` (441): split the 360-line `useEffect` into focused effects (data load · range/scale · drawing) and extract `useChartDrawing`; stabilize the unstable `a` (artifact) dependency so the chart isn't recreated every render. Cleanup (ResizeObserver + `chart.remove`) preserved. | med | M | TODO |

## Phase 3 — Provenance · a11y · tests

| ID | Task | Sev | Eff | Status |
|---|---|---|---|---|
| **FE-12** | `<ProvenanceFooter source as_of freshness cadence category>` shared component, composed by `ArtifactCard` / `SourceCard` / `FilingViewer` so the four trust signals render the same way everywhere (today they're split across headers/footers/tags). | high | M | TODO |
| **FE-13** | a11y pass: `SourceCard`'s `role="button"` div gets `tabIndex` + key handlers; grid widget toolbar buttons + drag/resize handles get `aria-label`s; opaque glyphs (⠿/✕/↻/🔔) get accessible names. (Modal a11y lands in FE-06.) | med | M | TODO |
| **FE-14** | *(optional, foundational)* add a test runner (vitest + @testing-library/react) and seed the high-value tests the audit wanted: TradeChart create/teardown lifecycle, FilingViewer highlight fallback chain, `toLayout` collision/compaction, and SSE-event parsing. | med | L | TODO |

---

## Deferred / rejected (value vs. risk)

- **BFF route factory / 40× dedup** — overstated: `proxyStudio`/`studioFetch` already exist; only the
  2 SSE routes need work (FE-05). No mass rewrite warranted.
- **`lib/alerts.ts` regex removal** — there is no regex; the cadence→trigger derivation is already
  table-driven (invariant #9 honored). Nothing to do.
- **Board state context / global store** — the modals don't currently mutate board state; prop-passing
  is fine. Revisit only if alerts gain inline-edit. No state library (Redux/Zustand) needed.
- **zod request validation in BFF** — studio-api already validates; adding a client-side schema layer
  is net-new surface, not a refactor. Out of scope.

## Per-task Definition of Done

`npx tsc --noEmit` clean · `next build` (or `docker compose build web`) succeeds · the affected surface
live-smoked (same UI/behavior) · no `localStorage`/provenance/sandbox/Gemini-only invariant violated ·
this file's **Status** flipped to `DONE` in the same commit, tagged with the `FE-id`.
