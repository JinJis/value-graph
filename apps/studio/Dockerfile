# ValueGraph Studio (Next.js). Build context = repo root (pnpm workspace; Studio
# depends on @valuegraph/graph-schema).
#   docker build -f apps/studio/Dockerfile -t valuegraph-studio .
FROM node:20-bookworm-slim

RUN corepack enable
WORKDIR /repo

COPY . .
# Next.js bakes rewrite destinations at BUILD time, so the engine URL must be set here
# (the "engine" host resolves at runtime over the compose network). Override with
# --build-arg ENGINE_INTERNAL_URL=... for non-compose builds.
ARG ENGINE_INTERNAL_URL=http://engine:8000
ENV ENGINE_INTERNAL_URL=$ENGINE_INTERNAL_URL
RUN pnpm install --frozen-lockfile && pnpm --filter @valuegraph/studio build

EXPOSE 3001
CMD ["pnpm", "--filter", "@valuegraph/studio", "exec", "next", "start", "-p", "3001", "-H", "0.0.0.0"]
