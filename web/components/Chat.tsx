"use client";

import { useEffect, useRef, useState } from "react";
import AgentBuilder, { Agent, Connector } from "./AgentBuilder";
import PromptLibrary from "./PromptLibrary";
import Watchlists, { Watchlist } from "./Watchlists";
import KpiPanel from "./KpiPanel";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Citation, CiteChip, SourceCard } from "./SourceCard";
import { SourceViewer } from "./SourceViewer";
import { Artifact, ArtifactCard, ChartAnnotations } from "./ArtifactCard";
import { Button, Chip, GuardrailLabel, Mascot, FreshnessDot } from "./ui";

type ToolUse = { name: string; label?: string };
type Think = { phase: string; text: string };
type ClarifyOption = { label: string; description?: string | null };
// CLARIFY-WITH-OPTIONS: the agent offers choices to scope a broad request; `origin` is the
// user's question the picks refine into a follow-up.
type Clarify = { prompt: string; options: ClarifyOption[]; multi: boolean; origin: string };
// A2A: a sub-agent dispatched on one facet of a complex request, shown as a live card.
type SubAgent = { id: number; title: string; status: string; sources?: number; steps?: number };
type Msg = { role: "user" | "assistant"; content: string; tools?: ToolUse[]; citations?: Citation[]; artifacts?: Artifact[]; refused?: boolean; used?: number[]; thinking?: Think[]; clarify?: Clarify; subagents?: SubAgent[] };

// Render the assistant's markdown (bold/bullets/tables/links). Links open out-of-tab.
const mdComponents = {
  a: (props: any) => <a {...props} target="_blank" rel="noreferrer" />,
};

// Collapse repeated tool calls to distinct labels (one answer can hit the same
// connector many times — show each source once, not eight identical rows).
function uniqueTools(tools?: ToolUse[]): ToolUse[] {
  const seen = new Map<string, ToolUse>();
  for (const t of tools || []) seen.set(t.label || t.name, t);
  return [...seen.values()];
}

// PH-THINK: the live reasoning stream — each step the agent narrates (analyze → look at a
// source → found data → synthesize), the latest one spinning, earlier ones checked.
function ThinkingLive({ steps }: { steps: Think[] }) {
  if (!steps.length) return null;
  return (
    <div className="thinking-live" aria-live="polite">
      {steps.map((s, j) => {
        const last = j === steps.length - 1;
        return (
          <div key={j} className={`tl-step ${last ? "active" : "done"}`}>
            <span className="tl-ic">{last ? <span className="tl-spin" /> : "✓"}</span>{s.text}
          </div>
        );
      })}
    </div>
  );
}

// CLARIFY-WITH-OPTIONS: render the agent's choices as chips. Single-pick → click runs it;
// multi-pick → toggle several then confirm. Picks compose a refined follow-up question.
function ClarifyChips(
  { clarify, disabled, onSubmit }:
  { clarify: Clarify; disabled?: boolean; onSubmit: (labels: string[]) => void },
) {
  const [sel, setSel] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setSel((prev) => { const n = new Set(prev); n.has(i) ? n.delete(i) : n.add(i); return n; });
  return (
    <div className="clarify">
      <div className="clarify-opts">
        {clarify.options.map((o, i) => (
          <button key={i} type="button" disabled={disabled}
            className={`clarify-chip ${clarify.multi && sel.has(i) ? "on" : ""}`}
            title={o.description || undefined}
            onClick={() => (clarify.multi ? toggle(i) : onSubmit([o.label]))}>
            <span className="clarify-label">{o.label}</span>
            {o.description ? <span className="clarify-desc">{o.description}</span> : null}
          </button>
        ))}
      </div>
      {clarify.multi && (
        <Button size="sm" disabled={disabled || sel.size === 0}
          onClick={() => onSubmit([...sel].sort((a, b) => a - b).map((i) => clarify.options[i].label))}>
          선택한 내용으로 진행 →
        </Button>
      )}
    </div>
  );
}

// A2A: live cards for the sub-agents researching each facet of a complex request in parallel.
function SubAgentCards({ subs }: { subs: SubAgent[] }) {
  if (!subs.length) return null;
  return (
    <div className="subagents">
      {subs.map((s) => (
        <div key={s.id} className={`subagent ${s.status}`}>
          <span className="sa-ic">{s.status === "done" ? "✓" : <span className="tl-spin" />}</span>
          <span className="sa-title">{s.title}</span>
          {s.status === "done" && <span className="sa-meta">{s.sources ?? 0} 근거</span>}
        </div>
      ))}
    </div>
  );
}

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
  const [view, setView] = useState<"desk" | "watch" | "board" | "kpi">("desk");
  const [handles, setHandles] = useState<string[]>([]);
  const [mention, setMention] = useState<string[]>([]); // open @-autocomplete suggestions
  const [pins, setPins] = useState<{ id: string; spec: Artifact }[]>([]);  // U3-03 Board
  const [viewer, setViewer] = useState<Citation | null>(null);  // expanded source viewer

  async function loadPins() {
    try {
      const r = await fetch("/api/board");
      if (r.ok) setPins((await r.json()).pinned ?? []);
    } catch {}
  }
  async function pinArtifact(a: Artifact) {
    try { await fetch("/api/board", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: a }) }); } catch {}
  }
  async function unpin(id: string) {
    try { await fetch(`/api/board/${id}`, { method: "DELETE" }); setPins((p) => p.filter((x) => x.id !== id)); } catch {}
  }
  async function refreshPin(id: string) {
    try {
      const r = await fetch(`/api/board/${id}/refresh`, { method: "POST" });
      if (r.ok) { const fresh = await r.json(); setPins((p) => p.map((x) => (x.id === id ? { ...x, spec: fresh.spec } : x))); }
    } catch {}
  }
  // PH-VIZ-5: persist the user's drawings on an already-pinned chart.
  async function annotatePin(id: string, ann: ChartAnnotations | null) {
    setPins((p) => p.map((x) => (x.id === id ? { ...x, spec: { ...x.spec, user_annotations: ann ?? undefined } } : x)));
    try {
      await fetch(`/api/board/${id}/annotate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_annotations: ann }),
      });
    } catch {}
  }

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
            else if (ev.type === "thinking") a.thinking = [...(a.thinking || []), { phase: ev.phase, text: ev.text }];
            else if (ev.type === "tool") a.tools = [...(a.tools || []), { name: ev.name, label: ev.label }];
            else if (ev.type === "clarify") {
              // origin = the user question these choices refine into a follow-up
              const origin = [...next].reverse().find((m) => m.role === "user")?.content || "";
              a.clarify = { prompt: ev.prompt, options: ev.options || [], multi: !!ev.multi, origin };
            }
            else if (ev.type === "subagent") {
              const list = [...(a.subagents || [])];
              const card: SubAgent = { id: ev.id, title: ev.title, status: ev.status, sources: ev.sources, steps: ev.steps };
              const k = list.findIndex((s) => s.id === ev.id);
              if (k >= 0) list[k] = card; else list.push(card);
              a.subagents = list;
            }
            else if (ev.type === "artifact" && ev.artifact) {
              const dup = (a.artifacts || []).some((x) => x.title === ev.artifact.title);
              if (!dup) a.artifacts = [...(a.artifacts || []), ev.artifact as Artifact];
            }
            else if (ev.type === "citation") {
              const cite: Citation = {
                tool: ev.tool, source: ev.source, url: ev.url, index: ev.index, kind: ev.kind,
                doc_type: ev.doc_type, as_of: ev.as_of, freshness: ev.freshness,
                snippet: ev.snippet, ticker: ev.ticker, page: ev.page,
                // PH-PROV2: carry the extracted table + the highlighted-filing screenshot URL,
                // else the Live Context / source card can never show the visual evidence.
                table: ev.table, evidence_image_url: ev.evidence_image_url,
              };
              const dup = (a.citations || []).some((c) => c.source === cite.source && c.url === cite.url);
              if (!dup) a.citations = [...(a.citations || []), cite];
            }
            // done: guardrail flag + the evidence set (which [n] actually backed the answer)
            else if (ev.type === "done") {
              if (ev.refused) a.refused = true;
              if (Array.isArray(ev.used)) a.used = ev.used;
              // PH-PROV3d: the done list is authoritative — its citations carry the evidence
              // image re-anchored on the figure the answer actually cited. Replace the streamed set.
              if (Array.isArray(ev.citations) && ev.citations.length) {
                a.citations = ev.citations.map((c: any) => ({
                  tool: c.tool, source: c.source, url: c.url, index: c.index, kind: c.kind,
                  doc_type: c.doc_type, as_of: c.as_of, freshness: c.freshness,
                  snippet: c.snippet, ticker: c.ticker, page: c.page,
                  table: c.table, evidence_image_url: c.evidence_image_url, used: c.used,
                }));
              }
              // PH-VIZ-2: the done list carries the chart artifacts enriched with sourced
              // event markers + price lines (added after later tool results landed).
              if (Array.isArray(ev.artifacts) && ev.artifacts.length) {
                a.artifacts = ev.artifacts as Artifact[];
              }
            }
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

  // Evidence for one message = the sources its answer actually used (else all consulted).
  const evidenceOf = (m: Msg): Citation[] => {
    const cites = m.citations ?? [];
    if (m.used && m.used.length) return cites.filter((c) => c.index != null && m.used!.includes(c.index));
    return cites;
  };

  return (
    <div className="shell no-right">
      <nav className="rail">
        <div className="rail-brand"><span className="mascot" aria-hidden /><span className="wordmark">ValueGraph</span></div>
        <button className="rail-new" onClick={() => { setMessages([]); setInput(""); setView("desk"); }}>
          <span className="ic">✎</span><span>새 대화</span>
        </button>
        <button className={`rail-item ${view === "desk" ? "on" : ""}`} onClick={() => setView("desk")}>
          <span className="ic">🏠</span><span className="lbl">데스크</span>
        </button>
        <button className={`rail-item ${view === "board" ? "on" : ""}`} onClick={() => { setView("board"); loadPins(); }}>
          <span className="ic">📊</span><span className="lbl">보드</span>
        </button>
        <button className={`rail-item ${view === "kpi" ? "on" : ""}`} onClick={() => setView("kpi")}>
          <span className="ic">📈</span><span className="lbl">지표</span>
        </button>
        <div className="rail-item soon" title="곧"><span className="ic">🧑‍💼</span><span className="lbl">분석가</span><span className="soon-tag">곧</span></div>
        <button className={`rail-item ${view === "watch" ? "on" : ""}`} onClick={() => setView("watch")}>
          <span className="ic">⭐</span><span className="lbl">관심</span>
        </button>
        <div className="rail-item soon" title="곧"><span className="ic">🔔</span><span className="lbl">브리프</span><span className="soon-tag">곧</span></div>
        <div className="rail-item soon" title="곧"><span className="ic">🛒</span><span className="lbl">갤러리</span><span className="soon-tag">곧</span></div>
        <div className="rail-spacer" />
        <div className="rail-foot">
          <span className="acct-ava" aria-hidden />
          <div className="acct-meta">
            <span className="acct-name" title={name}>{(name?.split("@")[0] ?? "me").slice(0, 12)}</span>
            <span className="acct-sub">tenant ✓</span>
          </div>
          <a href="/api/auth/signout" title="로그아웃">↩</a>
        </div>
      </nav>

      <div className="main">
        {view === "watch" ? (
          <Watchlists embedded onChanged={loadHandles} />
        ) : view === "kpi" ? (
          <KpiPanel onPin={pinArtifact} onExpand={setViewer} />
        ) : view === "board" ? (
          <div className="board">
            <div className="board-head"><h3>📊 보드</h3><span className="sub">핀한 라이브 아티팩트 · 열 때마다 출처·신선도 갱신</span></div>
            {pins.length === 0 ? (
              <p className="live-empty">아직 핀한 카드가 없어요. 답변의 차트 카드에서 <b>📌 핀</b>을 누르면 여기에 모여요.</p>
            ) : (
              <div className="board-grid">
                {pins.map((p) => <ArtifactCard key={p.id} a={p.spec} onRefresh={() => refreshPin(p.id)}
                  onRemove={() => unpin(p.id)} onEvidence={setViewer} onAnnotate={(ann) => annotatePin(p.id, ann)} />)}
              </div>
            )}
          </div>
        ) : (
          <>
            <header className="top">
              <div className="desk-id">
                <Mascot />
                <FreshnessDot f="fresh" />
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
              </div>
              <div className="agentbar">
                <Button variant="ghost" size="sm" onClick={() => setBuilder({ open: true, base: selected })}
                  title={selected ? "선택한 분석가 편집/복제" : "새 분석가 만들기"}>
                  {selected ? (selected.editable ? "⚙ 편집" : "⧉ 복제") : "＋ 분석가"}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setLibrary(true)} title="프롬프트 라이브러리">프롬프트</Button>
              </div>
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
                  {m.role === "assistant" && (m.thinking?.length || 0) > 0 && (
                    busy && i === messages.length - 1
                      ? <ThinkingLive steps={m.thinking!} />
                      : <details className="thinking-log">
                          <summary>🧠 분석 과정 · {m.thinking!.length}단계</summary>
                          {m.thinking!.map((t, j) => <div key={j} className="tl-step done"><span className="tl-ic">✓</span>{t.text}</div>)}
                        </details>
                  )}
                  {m.role === "assistant" && (m.subagents?.length || 0) > 0 && (
                    <SubAgentCards subs={m.subagents!} />
                  )}
                  <div className="bubble">
                    {m.content
                      ? (m.role === "assistant"
                          ? <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{m.content}</ReactMarkdown></div>
                          : m.content)
                      : (m.role === "assistant" && busy && !(m.thinking?.length) ? "…" : "")}
                  </div>
                  {m.role === "assistant" && m.clarify && (
                    <ClarifyChips clarify={m.clarify} disabled={busy}
                      onSubmit={(labels) => send(`${m.clarify!.origin} — ${labels.join(", ")}`)} />
                  )}
                  {m.role === "assistant" && m.refused && (
                    <GuardrailLabel>매수/매도·목표가·전망·점수는 제공하지 않아요 — 가드레일에서 자동 거절됩니다.</GuardrailLabel>
                  )}
                  {m.role === "assistant" && (m.artifacts?.length || 0) > 0 && (
                    <div className="artifacts">
                      {m.artifacts?.map((a, j) => <ArtifactCard key={`a${j}`} a={a} onPin={pinArtifact} onEvidence={setViewer} />)}
                    </div>
                  )}
                  {m.role === "assistant" && (() => {
                    const cites = m.citations ?? [];
                    const evidence = evidenceOf(m);
                    return (
                      <>
                        {evidence.length > 0 && (
                          <div className="answer-sources">
                            <div className="as-label">출처 {evidence.length}</div>
                            <div className="as-cards">
                              {evidence.map((c, j) => <SourceCard key={`s${j}`} c={c} onExpand={setViewer} />)}
                            </div>
                          </div>
                        )}
                        {(m.tools?.length || 0) > 0 && (
                          <details className="sources">
                            <summary>도구 {uniqueTools(m.tools).length}개{cites.length ? ` · 참고 출처 ${cites.length}` : ""}</summary>
                            {uniqueTools(m.tools).map((t, j) => <div key={`t${j}`} className="tool">🔧 {t.label || t.name}</div>)}
                            {cites.length > 0 && (
                              <div className="cite-chips">{cites.map((c, j) => <CiteChip key={`c${j}`} c={c} />)}</div>
                            )}
                          </details>
                        )}
                      </>
                    );
                  })()}
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
                  placeholder="무엇이든 물어보거나 — /프롬프트 · @그룹 호출…" disabled={busy} />
                <Button disabled={busy || !input.trim()}>보내기</Button>
              </form>
              {(input.match(/@([^\s@]+)/g) ?? []).length > 0 && (
                <div className="composer-meta">
                  {(input.match(/@([^\s@]+)/g) ?? []).slice(0, 3).map((h) => (
                    <Chip key={h} tone="accent">{h}</Chip>
                  ))}
                </div>
              )}
              <div className="disclaimer">투자 자문이 아니며, 가격 예측을 제공하지 않습니다.</div>
            </footer>
          </>
        )}
      </div>

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

      {viewer && <SourceViewer c={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}
