"use client";

import { useRef, useState } from "react";

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
        body: JSON.stringify({ messages: history.map((m) => ({ role: m.role, content: m.content })) }),
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

  return (
    <div className="app">
      <header className="top">
        <div className="brand">ValueGraph</div>
        <div className="who">{name} · <a href="/api/auth/signout">로그아웃</a></div>
      </header>

      <main className="chat" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            <h2>무엇이든 물어보세요</h2>
            <p>보유 종목, 뉴스, 시황, 경제 — 에이전트가 우리 데이터로 답하고 출처를 보여줍니다.</p>
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
        <form onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="메시지를 입력하세요…" disabled={busy} />
          <button className="btn" disabled={busy || !input.trim()}>보내기</button>
        </form>
        <div className="disclaimer">투자 자문이 아니며, 가격 예측을 제공하지 않습니다.</div>
      </footer>
    </div>
  );
}
