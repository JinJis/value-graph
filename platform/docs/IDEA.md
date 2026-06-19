# IDEA.md — product idea parking lot

> Exploratory product ideas, **not commitments.** The committed, dependency-ordered plan lives in
> [`ROADMAP.md`](./ROADMAP.md); the felt experience in [`UX_SPEC.md`](./UX_SPEC.md). An idea here is
> **promoted to the roadmap only with explicit approval** (same rule as any roadmap addition). Each entry:
> the idea, why it fits, a rough shape, what it touches, open questions. Newest on top.

---

## 1. The Research Desk as a *tool* — frameworks, live blocks, hypothesis journaling, portfolio check-up
*(captured 2026-06-19)*

**The idea.** Lean hard into "**not a chatbot, a productivity tool**" — a modern, web-native personal
Bloomberg + an investor's journaling/collaboration surface. The user does the thinking; we give them the
**best kitchen** (live, sourced data + frameworks) to cook with. Three motivating vignettes:
- **나만의 인사이트 노트** — today people screenshot, draw on tables, color-code, hand-collect… too fiddly.
  Instead: collect material conversationally (chat) → **pin to the Board** → spin it into a report. *(This is
  exactly the [Insight Canvas](#2-the-insight-canvas--a-composable-live-sourced-authoring-surface) below —
  the Board is its MVP substrate.)*
- **반려주식 관리 ("pet stocks")** — people get stuck holding losers and feel they must study endlessly;
  there's too much to learn. Make finding the *relevant, sourced* facts easy — and **kill hallucination**
  (every figure traced to its filing — this is what PH-PROV2 visual evidence is for).
- **포트폴리오 점검** — paste a screenshot of your brokerage portfolio → the desk checks it against
  frameworks/simulations: macro/micro, FX, P&L state, **risk-reward (손익비)** math, what-if "if I took
  action X, how could it move" laid out game-theory-style, and classic investor traps to watch.

**Why it fits — and why it's clean, legally.** Nobody thinks Excel / Notion / TradingView *recommends*
stocks; they're tools the user drives. Framing the desk as a **tool** (user pulls data and composes it),
not an advisor, keeps it clear of investment-advisory regulation — *and* matches our existing **guardrail**
(no advice / no forecasting, shown not hidden). Targets **high-engagement mid/advanced investors** building
their own philosophy → higher retention + willingness to pay (subscription, not BYO-key).

**Concrete features (sketches).**
- **Framework templates ("framework as a template").** Don't start from a blank board — ship famous
  investor models / book formulas as plug-in templates. *e.g.* 손익비 & Kelly-bet sizing board, Minervini
  VCP (volatility-contraction) tracker, rate-cycle asset-allocation view. (Generalizes prompt-import + the
  gallery clone pattern to **board/framework templates**.)
- **Live data blocks.** Notion-block-style: drop a watchlist company's live valuation/chart next to your
  prose (reuses the U3 artifact spec — live, sourced, freshness-stamped). = the Insight Canvas blocks.
- **Hypothesis-verification journaling.** At buy time, record *why* (the thesis). The system tracks the
  post-thesis price + fundamentals via the data plane and helps you **retrospect** ("was your hypothesis
  right?") weeks later. A deterministic, sourced feedback loop on your own decisions.
- **Portfolio check-up.** Import holdings (brokerage screenshot → OCR, or manual/CSV) → run framework
  calculators (risk-reward, exposure, concentration), **user-parameterized** what-if, and a "common traps"
  checklist. Calculators are deterministic; the data is sourced.

**What it touches.** `web` (board/canvas + template gallery — big lift) · `studio-api` (Note/Board template
models, portfolio model; mirror the prompt-import clone pattern) · `agent-engine` (framework calculators as
**deterministic tools**, never hand-rolled advice) · OCR for screenshot import (a new capability;
PaddleOCR/Upstage for KR) · governance/metering (PH-11/PH-12) for live-block refresh quotas.

**Open questions / risks.**
- **Guardrail tension (important).** "Simulation / what-if / strategy check / 손익비" must stay
  **user-parameterized + sourced + deterministic** — a calculator the user drives, never a model-generated
  forecast, score, or buy/sell suggestion. Reconcile every such feature with invariant #5 (no
  forecasting/advice, shown). If a framework implies a recommendation, it's out.
- **Hallucination = the whole brand.** Every figure must trace to a source (PH-PROV2). Frameworks compute
  from sourced inputs only; gaps drawn, never filled.
- **OCR reliability** for brokerage screenshots (formats vary, KR/EN); wrong import → wrong analysis. Needs
  a verify-before-use step.
- **Framework IP/licensing** (named methods/books) — attribute; check before shipping branded templates.
- **Surface sprawl.** chat (pull) · standing analysts (push) · Board/Canvas (compose) · portfolio (check) —
  decide the north-star ordering before committing; the Board is the shared substrate to build first.
- *User's open question to revisit:* which **investment frameworks/formulas (손익비, …)** to ship first as
  the flagship board templates?

**Status:** IDEA. Strong fit with the "research desk = tool" north star; **do not add to the roadmap without
approval.** Natural sequence: **Board (U3-03, done) → evaluate Canvas (#2) → framework templates → portfolio
check-up.** Depends on PH-PROV2 (no-hallucination) being solid first.

## 2. The Insight Canvas — a composable, live-sourced authoring surface
*(captured 2026-06-15)*

**The idea.** Professional investors organize their thinking by screenshotting charts/tables/filings and
pasting them into a blog post or research note. Those screenshots are **dead** — stale, unsourced,
un-refreshable. We already (a) pull any data through one LLM + data plane, (b) render it as **live, sourced
artifacts** (U3: charts/tables with provenance + freshness). So the natural evolution of the chat surface
is a **blog-/doc-like authoring canvas** where the analyst **writes their thesis in prose and drops live
artifacts anywhere in the text** — pulled the same way they ask in chat. A "living research note", not a
dead blog post.

**Why it fits (and is a real differentiator).**
- It's the same engine, one surface up: chat answers an ask; the canvas lets you **compose** many asks into
  a narrative. Artifacts stay **live** (refreshable, freshness-stamped, every figure carries its source) —
  this is *trust by construction* applied to authoring.
- Not a chatbot, not a BI dashboard, not Notion: a **sourced-insight authoring tool** for investors. The
  screenshot-to-blog workflow becomes native, and the output never goes stale silently.
- Composes cleanly with what's planned: **U3** artifacts are the embeddable blocks; **PH-4** source-preview
  cards are inline citations; the **Board** (U3-03) is the "untitled grid" version of a canvas (cards
  without prose); **U5 gallery** makes a note **publishable/cloneable** (others clone it with *their* data
  substituted → the ecosystem pillar, applied to notes); **PH-SOURCES** (reports/blogs/books) becomes the
  research feedstock writers cite.

**Rough shape (sketch, not a spec).**
- A `Note` / `Canvas` doc type: a block editor of **text blocks** + **artifact blocks**.
- Insert an artifact via a `/` command or by dragging a card from chat / the Board → embeds the artifact
  **spec** (not an image), so it re-fetches + re-stamps `as_of` on open. Gaps still drawn.
- Every embedded figure keeps its provenance chip + freshness dot; "stale → update" surfaces inline.
- Share/publish (Phase-2 ecosystem): publish a note like a gallery analyst; clone re-binds its data to the
  reader's watchlist/activations. Export = keep-live (link) or snapshot.

**What it touches.** `web` (block editor — the big lift) · `agent-engine`/`studio-api` (reuse the artifact
spec + a `Note` persistence model, mirrors `PinnedArtifact`) · governance (PH-12) if notes with licensed
data are published.

**Open questions / risks.**
- Block-editor complexity (build vs. adopt a minimal lib) — keep it small first (text + artifact blocks).
- Refresh cost/quotas for many live artifacts in one doc → ties to subscription metering (PH-11/PH-12).
- Relationship to the **Board**: Board = grid of live cards; Canvas = prose + live cards. Likely the Board
  is the MVP and the Canvas is "Board + narrative". Sequence: **U3-03 Board first, then evaluate the Canvas.**
- Authoring ≠ the "pull→push analyst" pillar — this is a third surface (compose), alongside chat (pull) and
  standing analysts (push). Worth deciding if/where it sits in the north star before committing.

**Status:** IDEA. Strong fit; **do not add to the roadmap without approval.** Natural earliest moment to
revisit: after **U3-03 (Board)** ships (the Board is the canvas's MVP substrate).
