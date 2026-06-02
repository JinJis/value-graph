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

### Run with Docker (full stack)

```bash
docker compose -f infra/docker-compose.yml up -d --build   # dbs + engine + studio + terminal
#  engine   -> http://localhost:8000/health
#  studio   -> http://localhost:3001/health
#  terminal -> http://localhost:3000/health
docker compose -f infra/docker-compose.yml down            # stop (volumes persist)
```

Databases only (run the services yourself with the commands below):

```bash
docker compose -f infra/docker-compose.yml up -d postgres neo4j redis
infra/smoke_test.sh                                        # verify all three reachable
uv run python -m services.engine.db.migrate                # apply Postgres + Neo4j migrations
```

Credentials default to `valuegraph` in local dev (override via `POSTGRES_*` /
`NEO4J_PASSWORD` / port env vars). Set `GOOGLE_API_KEY` for the engine's Gemini calls.

### Run the services directly (without Docker)

```bash
uv run uvicorn services.engine.main:app --reload   # Engine    -> :8000/health
pnpm --filter @valuegraph/studio dev               # Studio    -> :3001
pnpm --filter @valuegraph/terminal dev             # Terminal  -> :3000
```

### Checks

```bash
pnpm lint && pnpm typecheck && pnpm test
uv run ruff check services && uv run mypy services && uv run pytest services
```

Real services (FastAPI app, Next.js apps, Gemini router, DBs) land in later M0 tasks
(`M0-INFRA-02` … `M0-DB-06`). This scaffold is `[M0-REPO-01]`.
