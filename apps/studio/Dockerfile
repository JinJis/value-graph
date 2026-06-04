# ValueGraph Studio (Next.js). Build context = repo root (pnpm workspace; Studio
# depends on @valuegraph/graph-schema).
#   docker build -f apps/studio/Dockerfile -t valuegraph-studio .
FROM node:20-bookworm-slim

RUN corepack enable
WORKDIR /repo

COPY . .
# The engine proxy (app/engine/[...path]/route.ts) reads ENGINE_INTERNAL_URL at RUNTIME,
# so it need not be baked at build time — but we set it as the image default for compose
# (the "engine" host resolves over the compose network). Override at run time with -e.
ENV ENGINE_INTERNAL_URL=http://engine:8000
RUN pnpm install --frozen-lockfile && pnpm --filter @valuegraph/studio build

EXPOSE 3001
CMD ["pnpm", "--filter", "@valuegraph/studio", "exec", "next", "start", "-p", "3001", "-H", "0.0.0.0"]
