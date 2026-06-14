"use client";

import { useEffect, useRef, useState } from "react";
import AgentBuilder, { Agent, Connector } from "./AgentBuilder";
import PromptLibrary from "./PromptLibrary";
import Watchlists, { Watchlist } from "./Watchlists";

type Citation = { tool?: string; source?: string; url?: string };
type Msg = { role: "user" | "assistant"; content: string; tools?: { name: string }[]; citations?: Citation[] };

const EXAMPLES = [
  "삼성전자 최근 실적 알려줘",
  "AAPL 최근 주가 흐름",
  "Fed 기준금리 추이",
  "엔비디아 공급망·리스크 공시 요약",
];

export default function Chat({ name }: { name: string }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // agents
  const [agents, setAgents] = useState<Agent[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [agentId, setAgentId] = useState<string>(""); // "" = default agent
  const [builder, setBuilder] = useState<{ open: boolean; base: Agent | null }>({ open: false, base: null });
  const [library, setLibrary] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // shell view + watchlists / @groups
  const [view, setView] = useState<"desk" | "watch">("desk");
  const [handles, setHandles] = useState<string[]>([]);
  const [mention, setMention] = useState<string[]>([]); // open @-autocomplete suggestions

  async function loadAgents() {
    try {
      const r = await fetch("/api/agents");
      if (r.ok) setAgents((await r.json()).agents ?? []);
    } catch {}
  }
  async function loadHandles() {
    try {
      const r = await fetch("/api/watchlists");
      if (r.ok) setHandles(((await r.json()).watchlists ?? []).map((w: Watchlist) => w.name));
    } catch {}
  }
  useEffect(() => {
    loadAgents();
    loadHandles();
    (async () => {
      try {
        const r = await fetch("/api/connectors");
        if (r.ok) setConnectors((await r.json()).connectors ?? []);
      } catch {}
    })();
  }, []);

  // @handle autocomplete: when the text ends with "@token", suggest matching groups
  function onInput(v: string) {
    setInput(v);
    const m = v.match(/@([^\s@]*)$/);
    if (m) {
      const tok = m[1].toLowerCase();
      setMention(handles.filter((h) => h.toLowerCase().includes(tok)).slice(0, 6));
    } else setMention([]);
  }
  function pickHandle(h: string) {
    setInput((v) => v.replace(/@([^\s@]*)$/, `@${h} `));
    setMention([]);
    inputRef.current?.focus();
  }

  const selected = agents.find((a) => a.id === agentId) || null;

  async function send(text: string) {
    if (!text.trim() || busy) return;
    const history: Msg[] = [...messages, { role: "user", content: text }];
    setMessages([...history, { role: "assistant", content: "", tools: [], citations: [] }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history.map((m) => ({ role: m.role, content: m.content })),
          agent_id: agentId || null,
        }),
      });
      if (!res.body) throw new Error("no stream");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = block.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          let ev: any;
          try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
          setMessages((prev) => {
            const next = [...prev];
            const a = { ...next[next.length - 1] };
            if (ev.type === "token") a.content += ev.text || "";
            else if (ev.type === "tool") a.tools = [...(a.tools || []), { name: ev.name }];
            else if (ev.type === "citation") a.citations = [...(a.citations || []), { tool: ev.tool, source: ev.source, url: ev.url }];
            next[next.length - 1] = a;
            return next;
          });
          scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
        }
      }
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], content: "(문제가 발생했어요. 잠시 후 다시 시도해 주세요.)" };
        return next;
      });
    } finally {
      setBusy(false);
    }
  }

  function onSaved(saved: Agent, deletedId?: string) {
    setBuilder({ open: false, base: null });
    loadAgents();
    if (deletedId && agentId === deletedId) setAgentId("");
    else if (!deletedId) setAgentId(saved.id);
  }

  const liveCites = [...messages].reverse()
    .find((m) => m.role === "assistant" && (m.citations?.length || 0) > 0)?.citations ?? [];

  return (
    <div className={`shell ${view === "desk" ? "" : "no-right"}`}>
      <nav className="rail">
        <div className="rail-brand"><span className="mascot" aria-hidden /></div>
        <button className={`rail-item ${view === "desk" ? "on" : ""}`} onClick={() => setView("desk")}>
          <span className="ic">🏠</span>데스크
        </button>
        <div className="rail-item soon" title="곧"><span className="ic">📊</span>보드<span className="soon-tag">곧</span></div>
        <div className="rail-item soon" title="곧"><span className="ic">🧑‍💼</span>분석가<span className="soon-tag">곧</span></div>
        <button className={`rail-item ${view === "watch" ? "on" : ""}`} onClick={() => setView("watch")}>
          <span className="ic">⭐</span>관심
        </button>
        <div className="rail-item soon" title="곧"><span className="ic">🔔</span>브리프<span className="soon-tag">곧</span></div>
        <div className="rail-item soon" title="곧"><span className="ic">🛒</span>갤러리<span className="soon-tag">곧</span></div>
        <div className="rail-spacer" />
        <div className="rail-foot"><span title={name}>{(name?.split("@")[0] ?? "me").slice(0, 9)}</span><a href="/api/auth/signout">로그아웃</a></div>
      </nav>

      <div className="main">
        {view === "watch" ? (
          <Watchlists embedded onChanged={loadHandles} />
        ) : (
          <>
            <header className="top">
              <div className="agentbar">
                <select className="agentpick" value={agentId} onChange={(e) => setAgentId(e.target.value)} title="분석가 선택">
                  <option value="">기본 에이전트</option>
                  {agents.some((a) => a.is_template) && (
                    <optgroup label="제공 템플릿">
                      {agents.filter((a) => a.is_template).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </optgroup>
                  )}
                  {agents.some((a) => !a.is_template) && (
                    <optgroup label="내 에이전트">
                      {agents.filter((a) => !a.is_template).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </optgroup>
                  )}
                </select>
                <button className="btn ghost sm" onClick={() => setBuilder({ open: true, base: selected })}
                  title={selected ? "선택한 분석가 편집/복제" : "새 분석가 만들기"}>
                  {selected ? (selected.editable ? "편집" : "복제") : "＋ 분석가"}
                </button>
                <button className="btn ghost sm" onClick={() => setLibrary(true)} title="프롬프트 라이브러리">프롬프트</button>
              </div>
              <div className="who">데스크</div>
            </header>

            <main className="chat" ref={scrollRef}>
              {messages.length === 0 && (
                <div className="empty">
                  <h2>무엇이든 물어보세요</h2>
                  <p>보유 종목, 뉴스, 시황, 경제 — 분석가가 우리 데이터로 답하고 출처를 보여줍니다.</p>
                  {selected && <p className="agenthint">분석가: <b>{selected.name}</b>{selected.description ? ` · ${selected.description}` : ""}</p>}
                  <div className="examples">
                    {EXAMPLES.map((e) => (
                      <button key={e} className="chip" onClick={() => send(e)}>{e}</button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m, i) => (
                <div key={i} className={`msg ${m.role}`}>
                  <div className="bubble">{m.content || (m.role === "assistant" && busy ? "…" : "")}</div>
                  {m.role === "assistant" && ((m.tools?.length || 0) > 0 || (m.citations?.length || 0) > 0) && (
                    <details className="sources">
                      <summary>도구 · 출처{m.citations?.length ? ` (${m.citations.length})` : ""}</summary>
                      {m.tools?.map((t, j) => <div key={`t${j}`} className="tool">🔧 {t.name}</div>)}
                      {m.citations?.map((c, j) => (
                        <div key={`c${j}`} className="cite">
                          📎 {c.source || c.tool}
                          {c.url ? <> · <a href={c.url} target="_blank" rel="noreferrer">출처</a></> : null}
                        </div>
                      ))}
                    </details>
                  )}
                </div>
              ))}
            </main>

            <footer className="composer">
              {mention.length > 0 && (
                <div className="mention">
                  {mention.map((h, i) => (
                    <div key={h} className={`mention-item ${i === 0 ? "on" : ""}`}
                      onMouseDown={(e) => { e.preventDefault(); pickHandle(h); }}>
                      <span className="h">@{h}</span>
                      <span className="c">관심 그룹</span>
                    </div>
                  ))}
                </div>
              )}
              <form onSubmit={(e) => { e.preventDefault(); if (mention.length) { pickHandle(mention[0]); return; } send(input); }}>
                <input ref={inputRef} className="input" value={input} onChange={(e) => onInput(e.target.value)}
                  onBlur={() => setTimeout(() => setMention([]), 120)}
                  placeholder="메시지를 입력하거나 @그룹 으로 관심 종목을 호출…" disabled={busy} />
                <button className="btn" disabled={busy || !input.trim()}>보내기</button>
              </form>
              <div className="disclaimer">투자 자문이 아니며, 가격 예측을 제공하지 않습니다.</div>
            </footer>
          </>
        )}
      </div>

      {view === "desk" && (
        <aside className="rightpane">
          <h4>Live 컨텍스트</h4>
          <p className="sub">이번 답변에 쓰인 출처</p>
          <span className="live-label">⛔ 점수·전망 없음 · 원문만</span>
          {liveCites.length === 0 ? (
            <p className="live-empty">질문하면 답변에 사용된 출처가 여기에 모여요. 종목별 뉴스·공시 실시간 피드는 곧 추가됩니다.</p>
          ) : (
            liveCites.map((c, j) => (
              <div key={j} className="live-item">
                📎 {c.source || c.tool}
                {c.url ? <a href={c.url} target="_blank" rel="noreferrer" className="meta">{c.url}</a> : null}
              </div>
            ))
          )}
        </aside>
      )}

      {builder.open && (
        <AgentBuilder
          base={builder.base}
          connectors={connectors}
          onClose={() => setBuilder({ open: false, base: null })}
          onSaved={onSaved}
        />
      )}

      {library && (
        <PromptLibrary
          onClose={() => setLibrary(false)}
          onUse={(body) => {
            setInput(body);
            setLibrary(false);
            setTimeout(() => inputRef.current?.focus(), 0);
          }}
        />
      )}
    </div>
  );
}
