# ValueGraph Studio (Next.js). Build context = repo root (pnpm workspace; Studio
# depends on @valuegraph/graph-schema).
#   docker build -f apps/studio/Dockerfile -t valuegraph-studio .
FROM node:20-bookworm-slim

RUN corepack enable
WORKDIR /repo

COPY . .
RUN pnpm install --frozen-lockfile && pnpm --filter @valuegraph/studio build

EXPOSE 3001
CMD ["pnpm", "--filter", "@valuegraph/studio", "exec", "next", "start", "-p", "3001", "-H", "0.0.0.0"]
