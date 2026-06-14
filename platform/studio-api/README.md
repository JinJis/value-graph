# Studio API

The product backend behind the web app: maps a Google-authenticated user to a platform tenant,
stores conversations, and proxies streaming chat to the agent engine.

```
web BFF (X-Service-Token + X-User-Email) ─▶ studio-api ─▶ control-plane /admin (provision tenant/key)
                                                        └▶ agent-engine /agent/chat (SSE, tenant key)
```

- On first login it creates a tenant → project → API key + default connector activations (via the
  control-plane admin API) and caches it on the `User` row. **The platform key stays server-side.**
- `POST /chat/stream` proxies the agent-engine SSE to the browser while persisting the turn.
- `agents` / `prompts` / `integrations` tables are defined as seams for later phases (agent builder,
  prompt community, messengers).

## Endpoints
`POST /users/ensure` · `GET /conversations` · `GET /conversations/{id}/messages` · `POST /chat/stream`

## Run
```bash
cd platform/studio-api
uv sync --extra dev
uv run uvicorn studioapi.main:app --reload --port 8004
uv run pytest -q
```
Env (shared `../.env`): `SERVICE_TOKEN`, `CONTROL_PLANE_URL`, `ADMIN_TOKEN`, `AGENT_ENGINE_URL`, `DATABASE_URL`.
