#!/usr/bin/env bash
# End-to-end test of the whole platform via docker compose:
#   catalog -> tenant/key -> entitlement (403/200) -> data plane + RAG through the
#   gateway -> metering -> MCP tools. Exits non-zero on any failed assertion.
#
# Usage:  cd platform && bash scripts/e2e.sh
set -u
cd "$(dirname "$0")/.."

FAILS=0
ok()   { echo "  ok   $1"; }
fail() { echo "  FAIL $1"; FAILS=$((FAILS + 1)); }
check(){ [ "$2" = "$3" ] && ok "$1 ($2)" || fail "$1: got '$2' expected '$3'"; }
has()  { printf '%s' "$2" | grep -q "$3" && ok "$1" || fail "$1"; }
jget() { python3 -c "import json,sys;print(json.load(sys.stdin)$1)" 2>/dev/null || true; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

DP=http://127.0.0.1:8000; CP=http://127.0.0.1:8010; RAG=http://127.0.0.1:8002
A=(-H "X-Admin-Token: dev-admin-token"); J=(-H "Content-Type: application/json")
PRICE_Q="ticker=AAPL&market=US&interval=day&start_date=2024-01-02&end_date=2024-01-05"

echo "== bring up stack (build) =="
docker compose up --build -d || { echo "compose up failed"; exit 1; }
for _ in $(seq 1 40); do
  st=$(docker inspect --format '{{.State.Health.Status}}' valuegraph-platform-control-plane-1 2>/dev/null || echo none)
  [ "$st" = healthy ] && break; sleep 2
done
echo "  control-plane health: $(curl -s $CP/health)"

echo "== catalog =="
N=$(curl -s $DP/catalog | jget '["count"]'); check "data-plane catalog connectors>=8" "$([ "${N:-0}" -ge 8 ] && echo yes)" yes
NC=$(curl -s $CP/catalog | jget '["count"]'); check "gateway catalog passthrough>=8" "$([ "${NC:-0}" -ge 8 ] && echo yes)" yes

echo "== tenant / project / key =="
TID=$(curl -s "${A[@]}" "${J[@]}" -X POST $CP/admin/tenants -d '{"name":"E2E"}' | jget '["id"]')
PID=$(curl -s "${A[@]}" "${J[@]}" -X POST $CP/admin/tenants/$TID/projects -d '{"name":"p"}' | jget '["id"]')
KEY=$(curl -s "${A[@]}" "${J[@]}" -X POST $CP/admin/projects/$PID/keys -d '{"name":"k"}' | jget '["api_key"]')
[ -n "$KEY" ] && ok "key issued (${KEY:0:14}...)" || fail "key issuance"
H=(-H "X-API-KEY: $KEY")

echo "== entitlement: prices (yahoo) =="
check "no key -> 401" "$(code "$CP/prices?$PRICE_Q")" 401
check "not activated -> 403" "$(code "${H[@]}" "$CP/prices?$PRICE_Q")" 403
curl -s "${A[@]}" "${J[@]}" -X POST $CP/admin/projects/$PID/activations -d '{"connector_id":"yahoo"}' >/dev/null
R=$(curl -s -D /tmp/eh "${H[@]}" "$CP/prices?$PRICE_Q")
has "activated -> real AAPL prices" "$R" '"ticker":"AAPL"'
has "x-connector: yahoo header" "$(cat /tmp/eh)" 'x-connector: yahoo'

echo "== entitlement: company/facts (sec_edgar not activated) =="
check "sec_edgar not activated -> 403" "$(code "${H[@]}" "$CP/company/facts?ticker=AAPL&market=US")" 403

echo "== RAG through the gateway =="
curl -s "${J[@]}" -X POST $RAG/rag/ingest \
  -d '{"documents":[{"text":"Apple relies on a limited number of suppliers; TSMC fabricates its custom silicon chips.","source":"SEC EDGAR","doc_type":"10-K","ticker":"AAPL","url":"https://sec.gov/aapl"}]}' >/dev/null
check "rag not activated -> 403" "$(code "${H[@]}" "${J[@]}" -X POST $CP/rag/search -d '{"query":"Apple TSMC chips supplier"}')" 403
curl -s "${A[@]}" "${J[@]}" -X POST $CP/admin/projects/$PID/activations -d '{"connector_id":"rag"}' >/dev/null
RR=$(curl -s -D /tmp/rh "${H[@]}" "${J[@]}" -X POST $CP/rag/search -d '{"query":"Apple TSMC chips supplier","top_k":3}')
has "rag search -> provenance 'SEC EDGAR'" "$RR" 'SEC EDGAR'
has "x-connector: rag header" "$(cat /tmp/rh)" 'x-connector: rag'

echo "== metering =="
U=$(curl -s "${A[@]}" $CP/admin/projects/$PID/usage)
has "usage records yahoo" "$U" 'yahoo'
has "usage records rag" "$U" '"rag"'

echo "== MCP tools via gateway =="
MCP_OUT=$(cd mcp && MCP_GATEWAY_URL=$CP MCP_API_KEY=$KEY uv run python - <<'PY' 2>/dev/null
import asyncio
from mcpserver.tools import fetch_catalog, build_tools, tool_index, call_tool
async def main():
    idx = tool_index(build_tools(await fetch_catalog()))
    print("TOOLS", "yahoo__prices" in idx, "rag__search" in idx)
    r = await call_tool(idx["yahoo__prices"], {"ticker":"AAPL","interval":"day","start_date":"2024-01-02","end_date":"2024-01-05","market":"US"})
    print("CALL", r["status"], r["connector"])
asyncio.run(main())
PY
)
echo "$MCP_OUT" | sed 's/^/    /'
has "MCP exposes yahoo__prices + rag__search" "$MCP_OUT" 'TOOLS True True'
has "MCP yahoo call -> 200 via yahoo" "$MCP_OUT" 'CALL 200 yahoo'

echo "== teardown =="
docker compose down >/dev/null 2>&1

echo
if [ "$FAILS" -eq 0 ]; then echo "✅ E2E PASSED"; else echo "❌ E2E FAILED ($FAILS assertions)"; fi
exit $FAILS
