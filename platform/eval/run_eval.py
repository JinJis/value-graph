#!/usr/bin/env python3
"""Quality-evaluation harness for the investment-agent platform.

Drives each scenario in `scenarios.py` through the REAL product path:
  provision a user → create an agent with chosen data sources (studio-api /agents)
  → ask the question (studio-api /chat/stream) → parse the SSE → grade.

Graders check that the agent fetched from the right source (MCP/data-plane/RAG),
grounded the answer in real data, cited the source, and respected its data-source
restrictions / guardrails. An optional Gemini LLM-judge scores answer quality.

Needs the stack up (default ports). Stdlib only — run with system python3:
    cd platform && python3 eval/run_eval.py
Env: STUDIO_URL, RAG_URL, SERVICE_TOKEN, EVAL_USER, GOOGLE_API_KEY, AGENT_MODEL.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from scenarios import SCENARIOS  # noqa: E402

STUDIO = os.environ.get("STUDIO_URL", "http://127.0.0.1:8004")
RAG = os.environ.get("RAG_URL", "http://127.0.0.1:8002")
SVC = os.environ.get("SERVICE_TOKEN", "dev-service-token")
USER = os.environ.get("EVAL_USER", "eval@valuegraph.local")


def _envval(key: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return ""
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


GKEY = os.environ.get("GOOGLE_API_KEY") or _envval("GOOGLE_API_KEY")
JUDGE_MODEL = os.environ.get("AGENT_MODEL") or _envval("AGENT_MODEL") or "gemini-flash-latest"


# --- HTTP (stdlib) --------------------------------------------------------
def _request(method: str, url: str, body=None, headers=None, timeout=240) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def studio(method: str, path: str, body=None) -> tuple[int, dict]:
    headers = {"X-Service-Token": SVC, "X-User-Email": USER, "Content-Type": "application/json"}
    code, raw = _request(method, f"{STUDIO}{path}", body, headers)
    try:
        return code, json.loads(raw or b"{}")
    except ValueError:
        return code, {"_raw": raw.decode("utf-8", "replace")}


def chat(question: str, agent_id: str) -> dict:
    """POST /chat/stream and fold the SSE into a structured result."""
    headers = {"X-Service-Token": SVC, "X-User-Email": USER, "Content-Type": "application/json"}
    code, raw = _request("POST", f"{STUDIO}/chat/stream",
                         {"messages": [{"role": "user", "content": question}], "agent_id": agent_id}, headers)
    tools, statuses, cites, ans = [], [], [], []
    refused = None
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:])
        except ValueError:
            continue
        t = ev.get("type")
        if t == "tool":
            tools.append(ev.get("name"))
        elif t == "tool_result":
            statuses.append(ev.get("status"))
        elif t == "citation":
            if ev.get("source"):
                cites.append(ev["source"])
        elif t == "token":
            ans.append(ev.get("text", ""))
        elif t == "done":
            refused = ev.get("refused")
    return {"http": code, "tools": tools, "statuses": statuses, "citations": cites,
            "answer": "".join(ans).strip(), "refused": bool(refused)}


def rag_ingest(docs: list[dict]) -> None:
    _request("POST", f"{RAG}/rag/ingest", {"documents": docs}, {"Content-Type": "application/json"})


# --- LLM judge (Gemini REST; optional) ------------------------------------
def judge(question: str, answer: str, citations: list[str]) -> dict | None:
    if not GKEY or not answer:
        return None
    today = os.environ.get("EVAL_TODAY") or datetime.date.today().isoformat()
    prompt = (
        f"You are grading a financial-data assistant. Today's date is {today}. The figures in the ANSWER "
        "were retrieved LIVE from authoritative primary sources (SEC EDGAR, OpenDART, Bank of Korea, Yahoo "
        "Finance) and must be treated as GROUND TRUTH — do NOT penalise recent or 2025/2026 dates as "
        "'future' or 'hallucinated', and do not fact-check the numbers yourself (you cannot see today's "
        "live data). Grade ONLY: (a) relevance — does it answer the question; (b) specificity — concrete "
        "figures/facts with a source; (c) tone — states facts, no price predictions or buy/sell advice.\n\n"
        f"QUESTION: {question}\nCITED SOURCES: {', '.join(citations) or 'none'}\nANSWER: {answer}\n\n"
        'Return JSON: {"score": <int 1-5>, "reason": "<one sentence>"}'
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE_MODEL}:generateContent?key={GKEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    code, raw = _request("POST", url, payload, {"Content-Type": "application/json"}, timeout=120)
    if code != 200:
        return None
    try:
        data = json.loads(raw)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        out = json.loads(text)
        return {"score": int(out.get("score", 0)), "reason": str(out.get("reason", ""))[:160]}
    except Exception:
        return None


# --- graders --------------------------------------------------------------
def grade(checks: dict, r: dict) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    tools_joined = " ".join(t for t in r["tools"] if t)

    if "expect_connector" in checks:
        c = checks["expect_connector"]
        out.append((f"calls {c}", c in tools_joined, f"tools={r['tools']}"))
    if "forbid_connectors" in checks:
        bad = [c for c in checks["forbid_connectors"] if c in tools_joined]
        out.append(("avoids " + "/".join(checks["forbid_connectors"]), not bad, f"tools={r['tools']}"))
    if "expect_status" in checks:
        s = checks["expect_status"]
        out.append((f"tool status {s}", s in r["statuses"], f"statuses={r['statuses']}"))
    if "expect_cite" in checks:
        c = checks["expect_cite"]
        out.append((f"cites {c}", any(c in s for s in r["citations"]), f"cites={r['citations']}"))
    if "answer_regex" in checks:
        rx = checks["answer_regex"]
        out.append((f"answer matches /{rx}/", bool(re.search(rx, r["answer"])), r["answer"][:80]))
    if "answer_contains" in checks:
        for sub in checks["answer_contains"]:
            out.append((f"answer contains '{sub}'", sub.lower() in r["answer"].lower(), r["answer"][:80]))
    if "expect_refused" in checks:
        want = checks["expect_refused"]
        out.append((f"refused={want}", r["refused"] == want, f"refused={r['refused']}"))
    return out


# --- run ------------------------------------------------------------------
def main() -> int:
    print(f"== Quality eval — studio={STUDIO}  judge={'on (' + JUDGE_MODEL + ')' if GKEY else 'OFF (no GOOGLE_API_KEY)'} ==\n")
    code, _ = studio("POST", "/users/ensure")
    if code != 200:
        print(f"FATAL: could not provision eval user (studio /users/ensure -> {code}). Is the stack up?")
        return 2

    total_checks = passed_checks = 0
    judged: list[int] = []
    scenario_rows: list[tuple[str, int, int, str]] = []

    for sc in SCENARIOS:
        name = sc["name"]
        print(f"── {name}")
        if sc.get("rag_docs"):
            rag_ingest(sc["rag_docs"])
        ac, agent = studio("POST", "/agents", {
            "name": sc["agent"]["name"], "model": sc["agent"].get("model", "gemini"),
            "data_sources": sc["agent"]["data_sources"], "system_prompt": sc["agent"].get("system_prompt"),
        })
        if ac != 200 or "id" not in agent:
            print(f"   ! agent creation failed ({ac}) — skipping\n")
            scenario_rows.append((name, 0, 1, "agent-create-failed"))
            total_checks += 1
            continue
        r = chat(sc["question"], agent["id"])
        print(f"   Q: {sc['question']}")
        print(f"   tools={r['tools']} status={r['statuses']} cites={r['citations']} refused={r['refused']}")
        print(f"   A: {r['answer'][:200]}")

        results = grade(sc["checks"], r)
        for label, ok, detail in results:
            total_checks += 1
            passed_checks += 1 if ok else 0
            print(f"      [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok else f"   ({detail})"))

        jtxt = ""
        if sc["checks"].get("judge"):
            j = judge(sc["question"], r["answer"], r["citations"])
            if j:
                judged.append(j["score"])
                jtxt = f"judge={j['score']}/5 ({j['reason']})"
                print(f"      · {jtxt}")
        sp = sum(1 for _, ok, _ in results if ok)
        scenario_rows.append((name, sp, len(results), jtxt))
        print()

    print("== Summary ==")
    for name, sp, tot, jtxt in scenario_rows:
        bar = "✓" if sp == tot else "✗"
        print(f"  {bar} {name}: {sp}/{tot} checks" + (f" · {jtxt}" if jtxt else ""))
    pct = (passed_checks / total_checks * 100) if total_checks else 0
    print(f"\n  Deterministic checks: {passed_checks}/{total_checks} ({pct:.0f}%)")
    if judged:
        avg = sum(judged) / len(judged)
        print(f"  LLM-judge quality:    {avg:.2f}/5 avg over {len(judged)} answers")
    else:
        avg = None
        print("  LLM-judge quality:    (skipped — set GOOGLE_API_KEY to enable)")

    det_ok = passed_checks == total_checks
    judge_ok = avg is None or avg >= 3.5
    ok = det_ok and judge_ok
    print(f"\n{'✅ EVAL PASSED' if ok else '❌ EVAL BELOW BAR'} "
          f"(threshold: all deterministic checks + judge avg ≥ 3.5)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
