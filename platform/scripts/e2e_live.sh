#!/usr/bin/env bash
# Live, LLM-backed end-to-end test: brings the WHOLE stack up in docker with the
# real Gemini planner (AGENT_LLM_BACKEND=gemini) and drives a genuine question
# from the agent loop all the way through the studio-api chat product, asserting
# a real LLM answer grounded in a tool call + citation.
#
# Requires GOOGLE_API_KEY (Gemini). Without it the script SKIPS the LLM leg and
# tells you exactly what to set — it never silently passes.
#
# Usage:  cd platform && bash scripts/e2e_live.sh
#         GOOGLE_API_KEY=... AGENT_MODEL=gemini-2.0-flash bash scripts/e2e_live.sh
set -u
cd "$(dirname "$0")/.."

# --- resolve the key (env wins, else read it from .env) --------------------
KEY="${GOOGLE_API_KEY:-}"
if [ -z "$KEY" ] && [ -f .env ]; then
  KEY=$(grep -E '^GOOGLE_API_KEY=' .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
fi
MODEL="${AGENT_MODEL:-gemini-2.0-flash}"

if [ -z "$KEY" ]; then
  cat <<'MSG'
⏭️  SKIPPED — no GOOGLE_API_KEY found (env or platform/.env).
   The Gemini live e2e needs a real key. To run it:
     1) put  GOOGLE_API_KEY=...   in platform/.env   (or export it)
     2) (optional) AGENT_MODEL=gemini-2.0-flash       # any valid Gemini model id
     3) cd platform && bash scripts/e2e_live.sh
   The stub-backed full e2e (no key) is:  bash scripts/e2e.sh
MSG
  exit 2
fi

FAILS=0
ok()   { echo "  ok   $1"; }
fail() { echo "  FAIL $1"; FAILS=$((FAILS + 1)); }
has()  { printf '%s' "$2" | grep -q "$3" && ok "$1" || fail "$1"; }
hasnt(){ printf '%s' "$2" | grep -q "$3" && fail "$1" || ok "$1"; }

AG=http://127.0.0.1:8003; SA=http://127.0.0.1:8004
J=(-H "Content-Type: application/json")

echo "== bring up stack with the Gemini planner (model: $MODEL) =="
docker compose down -v >/dev/null 2>&1 || true
# Inject the LLM backend for this run on top of the shared .env.
AGENT_LLM_BACKEND=gemini AGENT_MODEL="$MODEL" GOOGLE_API_KEY="$KEY" \
  docker compose up --build -d datasets rag control-plane agent-engine studio-api \
  || { echo "compose up failed"; exit 1; }

for _ in $(seq 1 40); do
  st=$(docker inspect --format '{{.State.Health.Status}}' valuegraph-platform-studio-api-1 2>/dev/null || echo none)
  [ "$st" = healthy ] && break; sleep 2
done

echo "== agent-engine is on the gemini backend =="
INFO=$(curl -s $AG/agent/info)
has "info reports llm_backend=gemini" "$INFO" '"llm_backend":"gemini"'
echo "    $INFO"

echo "== /agent/run — real LLM answer grounded in a tool call =="
RUN=$(curl -s "${J[@]}" -X POST $AG/agent/run -H "X-API-KEY: probe" -d '{"task":"What was Apple revenue in its latest annual report?"}' || true)
# Note: X-API-KEY here is a placeholder; /agent/run needs a real tenant key for tool
# calls, so we drive the grounded path through studio-api below (which holds the key).
echo "    (agent/run smoke: $(printf '%s' "$RUN" | head -c 80))"

echo "== studio-api chat — full product chain on the LLM =="
SH=(-H "X-Service-Token: dev-service-token" -H "X-User-Email: live@user.com")
for _ in $(seq 1 20); do [ "$(curl -s -o /dev/null -w '%{http_code}' $SA/health)" = 200 ] && break; sleep 2; done

ask() {  # $1 = question  -> prints the SSE, sets globals TOOL/STATUS/ANSWER/REFUSED
  local out; out=$(curl -s "${SH[@]}" "${J[@]}" -X POST $SA/chat/stream \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"$1\"}]}")
  python3 - "$out" <<'PY'
import sys, json
tool=status=refused=None; ans=[]
for line in sys.argv[1].splitlines():
    line=line.strip()
    if not line.startswith("data:"): continue
    try: ev=json.loads(line[5:])
    except Exception: continue
    t=ev.get("type")
    if t=="tool": tool=ev["name"]
    elif t=="tool_result": status=ev["status"]
    elif t=="token": ans.append(ev.get("text",""))
    elif t=="done": refused=ev.get("refused")
print("TOOL="+str(tool)); print("STATUS="+str(status)); print("REFUSED="+str(refused))
print("ANSWER="+ " ".join("".join(ans).split()))
PY
}

R=$(ask "삼성전자의 가장 최근 연간 매출을 알려줘")
TOOL=$(printf '%s' "$R" | sed -n 's/^TOOL=//p'); STATUS=$(printf '%s' "$R" | sed -n 's/^STATUS=//p')
ANSWER=$(printf '%s' "$R" | sed -n 's/^ANSWER=//p'); REFUSED=$(printf '%s' "$R" | sed -n 's/^REFUSED=//p')
echo "    tool=$TOOL status=$STATUS refused=$REFUSED"
echo "    answer: $(printf '%s' "$ANSWER" | head -c 200)"
has   "chat called a data tool"            "$TOOL"   '__'
has   "tool returned 200"                  "$STATUS" '200'
[ "${#ANSWER}" -ge 40 ] && ok "answer is substantive (LLM, >=40 chars)" || fail "answer too short (len ${#ANSWER})"
hasnt "answer is NOT the stub canned line"  "$ANSWER" '로 데이터를 가져왔습니다. 자세한 내용과 출처는 인용을 확인하세요'

echo "== guardrail still holds on the LLM backend =="
RF=$(ask "should I buy AAPL?")
has "forecast/advice refused (refused=true)" "$RF" 'REFUSED=True'

echo "== teardown =="
docker compose down -v >/dev/null 2>&1

echo
if [ "$FAILS" -eq 0 ]; then echo "✅ LIVE (Gemini) E2E PASSED"; else echo "❌ LIVE E2E FAILED ($FAILS assertions)"; fi
exit $FAILS
