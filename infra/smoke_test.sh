#!/usr/bin/env bash
# [M0-INFRA-02] Connection smoke-test for the ValueGraph local infra stack.
#
# Verifies each database is not just "up" but actually reachable and answering,
# using each container's own client (no host-side drivers required):
#   - Postgres : pg_isready
#   - Redis    : redis-cli ping  -> PONG
#   - Neo4j    : cypher-shell 'RETURN 1'  (proves Bolt + auth)
#
# Usage:  infra/smoke_test.sh
# Exit 0 = all three reachable; non-zero = at least one failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$SCRIPT_DIR/docker-compose.yml}"
DC=(docker compose -f "$COMPOSE_FILE")

POSTGRES_USER="${POSTGRES_USER:-valuegraph}"
POSTGRES_DB="${POSTGRES_DB:-valuegraph}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-valuegraph}"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

echo "==> Postgres"
"${DC[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  || fail "postgres not accepting connections"

echo "==> Redis"
pong="$("${DC[@]}" exec -T redis redis-cli ping | tr -d '\r')"
[ "$pong" = "PONG" ] || fail "redis did not answer PONG (got: '$pong')"
echo "redis: PONG"

echo "==> Neo4j"
"${DC[@]}" exec -T neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" 'RETURN 1 AS ok;' \
  || fail "neo4j Bolt query failed"

echo
echo "OK: Neo4j + Postgres + Redis all reachable."
