# ValueGraph Terminal (Next.js). Build context = repo root (pnpm workspace).
#   docker build -f apps/terminal/Dockerfile -t valuegraph-terminal .
FROM node:20-bookworm-slim

RUN corepack enable
WORKDIR /repo

COPY . .
# Next.js bakes rewrite destinations at BUILD time, so the engine URL must be set here
# (the "engine" host resolves at runtime over the compose network). Override with
# --build-arg ENGINE_INTERNAL_URL=... for non-compose builds.
ARG ENGINE_INTERNAL_URL=http://engine:8000
ENV ENGINE_INTERNAL_URL=$ENGINE_INTERNAL_URL
RUN pnpm install --frozen-lockfile && pnpm --filter @valuegraph/terminal build

EXPOSE 3000
CMD ["pnpm", "--filter", "@valuegraph/terminal", "exec", "next", "start", "-p", "3000", "-H", "0.0.0.0"]
