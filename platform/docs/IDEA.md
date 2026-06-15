# IDEA.md — product idea parking lot

> Exploratory product ideas, **not commitments.** The committed, dependency-ordered plan lives in
> [`ROADMAP.md`](./ROADMAP.md); the felt experience in [`UX_SPEC.md`](./UX_SPEC.md). An idea here is
> **promoted to the roadmap only with explicit approval** (same rule as any roadmap addition). Each entry:
> the idea, why it fits, a rough shape, what it touches, open questions. Newest on top.

---

## 1. The Insight Canvas — a composable, live-sourced authoring surface
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
