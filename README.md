# ValueGraph

B2C, visualization-first supply-chain intelligence — companies as nodes (size = live market
cap), supplier→customer trades as edges, rendered in a WebGL 3D canvas with honest uncertainty.

> Canonical docs: **`ValueGraph_PRD_v5.md`** (what/why) · **`ValueGraph_BUILD_PLAN.md`** (ordered
> tasks + acceptance criteria) · **`CLAUDE.md`** (engineering rules). Build one milestone at a
> time, one task per PR.

## Layout (monorepo)

```
apps/studio      Admin back-office (Next.js)            — stub
apps/terminal    User front-end (Next.js + R3F)         — stub
services/engine  FastAPI + LangGraph — CVE / Gemini      — stub
services/pipeline Feed ingestion, triggers, scheduler    — stub
packages/graph-schema  Node/edge/claim type defs (SSOT)
packages/ui      Shared tokens / components
infra            docker-compose, db init, migrations
```

## Getting started

```bash
pnpm install        # JS workspaces (apps/*, packages/*)
uv sync             # Python services + dev tooling (ruff, mypy, pytest)
```

### Run the stubs

```bash
pnpm --filter @valuegraph/studio dev      # Studio stub
pnpm --filter @valuegraph/terminal dev    # Terminal stub
uv run python -m services.engine          # Engine stub
uv run python -m services.pipeline        # Pipeline stub
```

### Checks

```bash
pnpm lint && pnpm typecheck && pnpm test
uv run ruff check services && uv run mypy services && uv run pytest services
```

Real services (FastAPI app, Next.js apps, Gemini router, DBs) land in later M0 tasks
(`M0-INFRA-02` … `M0-DB-06`). This scaffold is `[M0-REPO-01]`.
