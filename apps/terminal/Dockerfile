# ValueGraph Terminal (Next.js). Build context = repo root (pnpm workspace).
#   docker build -f apps/terminal/Dockerfile -t valuegraph-terminal .
FROM node:20-bookworm-slim

RUN corepack enable
WORKDIR /repo

COPY . .
RUN pnpm install --frozen-lockfile && pnpm --filter @valuegraph/terminal build

EXPOSE 3000
CMD ["pnpm", "--filter", "@valuegraph/terminal", "exec", "next", "start", "-p", "3000", "-H", "0.0.0.0"]
