# DESIGN_SYSTEM.md — ValueGraph component templates

> Source of truth for the **web UI visual language**, derived 1:1 from the user's
> wireframe (`docs/wireframe.dc.html`, open it with `wireframe-support.js`; intent in
> `docs/wireframe-chat.md`). The wireframe is **mid-fidelity light grayscale**: white
> cards on a light gray page, near-black ink for actions, and **the freshness/trust
> signals are the only saturated color**. Implemented in `web/app/globals.css` `:root`
> + component classes; every web component consumes these tokens — **don't hardcode
> hex in components** (the one exception is `ArtifactCard`'s SVG stroke palette, which
> needs literal colors for `<path stroke>`).

## 1. Principles (from the wireframe)
1. **Grayscale by default, trust = the only color.** Black→gray→white everywhere;
   saturated hue appears *only* in freshness dots (🟢🟡🔴⚪) and the calm indigo accent
   used for citations/@groups.
2. **Every artifact card ends in a trust line** — `출처 · as_of · 신선도`. Non-negotiable.
3. **The guardrail is a visible label, not fine print.** Amber callout on the Live feed,
   the builder, news cards, and on any refused turn.
4. **Two typefaces.** `Space Grotesk` for UI; `Space Mono` for every number, ticker,
   timestamp, code, and `[n]` citation marker. (`Caveat` is the wireframe's *designer
   annotation* hand — it is **not** a product typeface; do not ship it in the app UI.)
5. **Hairlines, soft radius, soft shadow.** 1px borders, 9–12px card radius, the two
   shadow recipes below. No heavy chrome.

## 2. Tokens (`globals.css :root`)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#E9E9EB` | app backdrop (behind the shell) |
| `--panel` | `#ffffff` | primary card / surface |
| `--panel-2` | `#FAFAFB` | subtle inset (rails, chat scroll, raised insets) |
| `--panel-3` | `#FCFCFD` | faintest surface |
| `--text` | `#26262A` | primary text |
| `--text-2` | `#4A4A50` | secondary body |
| `--muted` | `#86868C` | meta / labels |
| `--faint` | `#A6A6AC` | placeholder / faintest |
| `--line` | `#E4E4E7` | default hairline |
| `--line-2` | `#D8D8DC` | stronger card outline |
| `--line-3` | `#F0F0F2` | faintest divider |
| `--ink` / `--paper` | `#1A1B1E` | near-black: primary action bg, active rail, dark accents |
| `--on-ink` | `#ffffff` | text on ink |
| `--focus` | `#1A1B1E` | active input border |
| `--accent` | `#6E72B0` | citations `[n]`, @group, links (calm indigo, used sparingly) |
| `--accent-bg` / `--accent-fg` | `#EEF0F6` / `#5A5E86` | @group chips |
| `--fresh` / `--aging` / `--stale` / `--gap` | `#1FA463` / `#D9A300` / `#D1483A` / `#A6A6AC` | freshness dots — the only saturated colors |
| `--warn-fg` / `--warn-bg` / `--warn-line` | `#8A6A00` / `#FBF3DA` / `#EFE0AE` | guardrail label |
| `--mark` | `#FCEFC4` | verbatim highlight inside filing snippets |
| `--ui` | `Space Grotesk, …` | UI font |
| `--mono` | `Space Mono, …` | numbers/tickers/timestamps/code |
| `--shadow-card` | `0 1px 2px rgba(0,0,0,.04), 0 6px 20px rgba(0,0,0,.04)` | cards |
| `--shadow-pop` | `0 8px 26px rgba(0,0,0,.06)` | modals / popovers |

## 3. Component templates (class → wireframe section)
- **App shell** `.shell` (rail · main · rightpane) — wireframe **A**. Rail = 6 returning
  destinations; right pane = Live context with the guardrail label always pinned.
- **Message bubbles** `.msg .bubble` — wireframe A/B. User bubble = **ink** (`--ink` bg,
  light text); assistant = white card with hairline. `[n]` markers (`.anch`) = `--accent`.
- **Inline artifact card** `.artifact` — wireframe A/B/D. Title row (freshness dot + 차트/표
  · ↻ · 📌), SVG chart, then the **trust line** (`출처 · as_of · 신선도`, drawn gaps).
- **Source-preview card** `.scard` (`.filing`/`.news`/`.metric`/`.data`) — wireframe **C**.
  Type-aware: filing shows a verbatim snippet (`--mark` highlight), news ends in the
  context-not-forecast note. Always a freshness dot + `as_of`.
- **Trust legend** `.legend` — wireframe C. One legend, reused wherever a dot appears.
  Shows **freshness** (computed). Confidence tiers (verified/derived/estimated) are the
  *spec intent* (wireframe C) but are **not rendered live** until the backend emits a
  `confidence` field — we don't fake it (honesty-over-fake-data).
- **Guardrail label** `.guard` — wireframe C/E/G. Amber callout; shown on the Live feed,
  the builder, news cards, and on any **refused** turn (the `done` SSE `refused` flag).
- **Board** `.board` / `.board-grid` — wireframe **D**. Pinned artifacts; each remembers
  tool+args and re-fetches a fresh `as_of` on open.
- **Builder modal** `.modal` + `.src-row`/`.tool-list` — wireframe **E**. Data-source rows
  expand to reveal the tools inside (transparency); guardrail label is always present.
- **Watchlists / @groups** `.wl-*` — wireframe **F**. Search → ⭐ favorite into a named
  `@handle` group; that handle is the unit the composer and builder bind to.
- **Prompt library** `.tabs`/`.prompt-card` — mine ↔ community, clone-import pattern.

## 4. Rules
- Consume tokens; never hardcode hex in components (except SVG strokes).
- Numbers, tickers, timestamps, `[n]` → `.mono`.
- Any user-visible figure shows source + as_of + freshness.
- Guardrail label is visible, never hidden behind a tooltip.
- Korean user-facing strings stay inline for now (i18n layer is a later task).
