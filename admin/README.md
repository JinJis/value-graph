# admin — Django-admin-style control panel

One login, then **browse and edit every table** across the platform's databases
(control-plane · studio · data plane) plus an **operations console** for the runtime
pieces (data-pipeline scheduler, self-test, RAG ingest/search, MCP/catalog).

- **CRUD over every table** — [sqladmin](https://aminalaee.dev/sqladmin/) auto-generates
  list/create/edit/delete views by **reflecting** each service's SQLite DB (no model
  imports, no coupling). Mount the three data volumes and it discovers the schema.
- **Ops console** — live status (catalog tool count, RAG embedder, scheduler state,
  store rows) + actions: run/pause/resume ingestion, run the data-plane self-test,
  ingest a RAG document, run a semantic search.
- **Auth** — a single session login gates the whole panel, including the mounted
  admin sub-apps. Set `ADMINUI_USERNAME` / `ADMINUI_PASSWORD` (defaults `admin`/`admin`).

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
