#!/usr/bin/env bash
# One command to run EVERYTHING: per-service unit tests, the web build, all three
# docker-compose e2e harnesses, and the quality eval. Docker is required (the e2e
# + eval bring the stack up via `docker compose`).
#
#   cd platform && bash scripts/test_all.sh
#
# The live-Gemini e2e and the eval need GOOGLE_API_KEY (in platform/.env or env);
# without it the live e2e is skipped and the eval runs structural checks only.
set -u
cd "$(dirname "$0")/.."
FAIL=0
step() { echo; echo "============================================================"; echo "== $1"; echo "============================================================"; }

step "Unit tests (per service)"
for d in datasets control-plane mcp rag agent-engine studio-api; do
  echo "-- $d"
  ( cd "$d" && rm -f studio.db; uv run pytest -q ) || FAIL=1
done
echo "-- rag semantic (real oss-cpu embeddings)"
( cd rag && uv run --extra oss pytest -q tests/test_rag_semantic.py ) || FAIL=1

step "Web build"
( cd web && npm run build >/dev/null 2>&1 ) && echo "  web build ok" || { echo "  web build FAILED"; FAIL=1; }

step "Docker e2e — stub full stack (deterministic, no key)"
bash scripts/e2e.sh || FAIL=1

step "Docker e2e — functional (real data + MCP + semantic RAG, no key)"
bash scripts/e2e_functional.sh || FAIL=1

step "Docker e2e — live Gemini (skips cleanly without GOOGLE_API_KEY)"
bash scripts/e2e_live.sh; rc=$?
if [ "$rc" = 2 ]; then echo "  (skipped — no GOOGLE_API_KEY)"; elif [ "$rc" != 0 ]; then FAIL=1; fi

step "Quality eval (brings the stack up, scores answers)"
docker compose up -d >/dev/null 2>&1
for _ in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8004/health 2>/dev/null)" = 200 ] && break; sleep 2
done
python3 eval/run_eval.py || FAIL=1

echo
if [ "$FAIL" = 0 ]; then echo "✅ ALL TESTS PASSED"; else echo "❌ SOME TESTS FAILED"; fi
exit "$FAIL"
