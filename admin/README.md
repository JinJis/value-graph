# admin — operations console

One login, then a **left-nav mission-control** over the whole platform, organized by
operator job-to-be-done. Out-of-band (not in the request path).

- **Overview** — at-a-glance tiles (data sources, catalog tools, RAG embedder, scheduler,
  store facts, running jobs) + per-subsystem health dots + recent errors.
- **Catalog** — live from the manifest (`/catalog` · `/rag/info` · `/agent/info`): every
  data source/connector (markets · license · key-required), each resource → REST path →
  **MCP tool** (`{connector}__{resource}`), plus RAG + agent backends. Never hand-maintained.
- **Pipelines** — every ingest/precompute job (backfill · evidence PDFs · news → RAG ·
  scheduler) as a **live progress card**, auto-refreshing while running, with trigger/
  pause/resume/self-test controls. Driven by `/admin/jobs` · `/admin/scheduler`.
- **Data** — ingestion-store coverage by market (empty-state drawn, not silent), RAG
  backends, stored-rows-per-table.
- **Users** — control-plane tenants → projects → API keys → activations (entitlements) →
  usage, plus studio users.
- **DB browser** — our **own styled CRUD** (view · edit · create · delete) over every
  **reflected** service table (no model imports, no coupling). Replaces sqladmin so there
  is **no unstyled raw-HTML fallback**; all links are relative (proxy/tunnel-safe).
- **Auth** — a single session login gates everything. Set `ADMINUI_USERNAME` /
  `ADMINUI_PASSWORD` (defaults `admin`/`admin`).

## Run (in the stack)

```bash
docker compose up -d admin          # http://localhost:8005  (login: admin / admin)
```

It mounts each service's data volume read-write:

| DB | volume → path | tables |
|---|---|---|
| control-plane | `controlplane_data` → `/dbs/controlplane/controlplane.db` | tenants · projects · api_keys · activations · usage_events · audit_logs |
| studio-api | `studio_data` → `/dbs/studio/studio.db` | users · conversations · messages · agents · prompts · integrations |
| data plane | `datasets_data` → `/dbs/datasets/datasets.db` | financial_facts (ingestion store) |

## Test

```bash
cd admin && uv run --extra dev pytest -q
```

> Editing a live SQLite DB while its service runs is fine (WAL), but it's a power tool —
> there are no app-level validations here, so it can write states the services wouldn't.
