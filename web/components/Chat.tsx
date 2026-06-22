"use client";

import { useEffect, useRef, useState } from "react";
import AgentBuilder, { Agent, Category } from "./AgentBuilder";
import BoardCanvas from "./BoardCanvas";
import PinPicker from "./PinPicker";
import PromptLibrary from "./PromptLibrary";
import PromptWaterfall, { WaterfallPrompt } from "./PromptWaterfall";
import Watchlists, { Watchlist } from "./Watchlists";
import KpiPanel from "./KpiPanel";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Citation, SourceCard } from "./SourceCard";
import { SourceViewer } from "./SourceViewer";
import { Artifact, ArtifactCard } from "./ArtifactCard";
import { Button, Chip, GuardrailLabel, Mascot, FreshnessDot } from "./ui";

type ToolUse = { name: string; label?: string };
type Think = { phase: string; text: string };
type ClarifyOption = { label: string; description?: string | null };
// CLARIFY-WITH-OPTIONS: the agent offers choices to scope a broad request; `origin` is the
// user's question the picks refine into a follow-up.
type Clarify = { prompt: string; options: ClarifyOption[]; multi: boolean; origin: string };
// A2A: a sub-agent dispatched on one facet of a complex request, shown as a live card.
type SubAgent = { id: number; title: string; status: string; sources?: number; steps?: number };
type Msg = { role: "user" | "assistant"; content: string; tools?: ToolUse[]; citations?: Citation[]; artifacts?: Artifact[]; refused?: boolean; used?: number[]; thinking?: Think[]; clarify?: Clarify; subagents?: SubAgent[]; suggestions?: string[] };

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
  // background-run tracking: which conversation is currently DISPLAYED, and which one is
  // actively being streamed into the UI. Generation lives server-side, so leaving a chat
  // just stops rendering here (the server keeps going); re-entering resumes via its run.
  const viewConvRef = useRef<string | null>(null);
  const streamConvRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // agents
  const [agents, setAgents] = useState<Agent[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [libPrompts, setLibPrompts] = useState<WaterfallPrompt[]>([]);
  const [agentId, setAgentId] = useState<string>(""); // "" = default agent
  const [builder, setBuilder] = useState<{ open: boolean; base: Agent | null }>({ open: false, base: null });
  const [library, setLibrary] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // shell view + watchlists / @groups
  const [view, setView] = useState<"desk" | "watch" | "board" | "kpi">("desk");
  const [handles, setHandles] = useState<string[]>([]);
  const [mention, setMention] = useState<string[]>([]); // open @-autocomplete suggestions
  const [pinTarget, setPinTarget] = useState<any | null>(null);  // asset awaiting a board-picker pin
  const [viewer, setViewer] = useState<Citation | null>(null);  // expanded source viewer
  // chat session/history — persisted in studio-api; resume a past conversation.
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [convs, setConvs] = useState<{ id: string; title: string }[]>([]);

  async function loadHistory() {
    try {
      const r = await fetch("/api/conversations");
      if (r.ok) setConvs((await r.json()).conversations ?? []);
    } catch {}
  }
  async function openConversation(id: string) {
    viewConvRef.current = id;   // claim the view first so any other stream stops rendering
    setConversationId(id);
    setView("desk");
    setBusy(false);
    try {
      const r = await fetch(`/api/conversations/${id}/messages`);
      if (!r.ok) return;
      const msgs = ((await r.json()).messages ?? []) as { role: string; content: string; citations?: Citation[] }[];
      setMessages(msgs.map((m) => ({
        role: m.role === "assistant" ? "assistant" : "user",
        content: m.content,
        citations: m.citations ?? [],
        used: (m.citations ?? []).map((c) => c.index).filter((n): n is number => n != null),
      })));
      // resume an in-flight answer: if this conversation is still generating, tail its run live
      const ar = await fetch(`/api/conversations/${id}/active-run`);
      const runId = ar.ok ? (await ar.json()).run_id : null;
      if (runId && viewConvRef.current === id) await tailRun(id, runId);
    } catch {}
  }
  function newChat() {
    viewConvRef.current = null;
    setMessages([]); setConversationId(null); setInput("");
    setView("desk");
    setBusy(false);
  }

  // Pin anything (chart/table artifact, source card) → open the board picker (choose board[s]).
  function pinArtifact(a: Artifact) { setPinTarget(a); }
  function pinCitation(c: Citation) {
    // a source/evidence/provenance card pinned as a board asset (kind="source").
    setPinTarget({ kind: "source", title: c.source || c.ticker || "출처", ...c });
  }

  async function loadAgents() {
    try {
      const r = await fetch("/api/agents");
      if (!r.ok) return;
      const list: Agent[] = (await r.json()).agents ?? [];
      setAgents(list);
      // land on the fully-loaded Gemini default agent (tpl_desk), not the bare/stub default
      const def = list.find((x) => x.id === "tpl_desk") || list.find((x) => x.is_template);
      if (def) setAgentId((prev) => prev || def.id);
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
    loadHistory();
    (async () => {
      try {
        const r = await fetch("/api/connectors");
        if (r.ok) setCategories((await r.json()).categories ?? []);
      } catch {}
    })();
    (async () => {
      try {
        const r = await fetch("/api/prompts/community");
        if (r.ok) setLibPrompts((await r.json()).prompts ?? []);
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

  // {tickers}/{ticker} placeholder fill — from a prompt-library import. Click a watchlist group
  // or search a company; the chosen value replaces the first placeholder in the box.
  const [tkQuery, setTkQuery] = useState("");
  const [tkRes, setTkRes] = useState<{ ticker: string; name?: string; market?: string }[]>([]);
  const hasPlaceholder = /\{tickers?\}/i.test(input);  // matches {TICKER}/{TICKERS}/{ticker}/{tickers}
  async function searchTicker(q: string) {
    setTkQuery(q);
    if (!q.trim()) { setTkRes([]); return; }
    try {
      const [us, kr] = await Promise.all([
        fetch(`/api/company/search?q=${encodeURIComponent(q)}&market=US&limit=4`).then((r) => (r.ok ? r.json() : { results: [] })),
        fetch(`/api/company/search?q=${encodeURIComponent(q)}&market=KR&limit=4`).then((r) => (r.ok ? r.json() : { results: [] })),
      ]);
      setTkRes([...(us.results || []), ...(kr.results || [])].slice(0, 8));
    } catch { setTkRes([]); }
  }
  function fillPlaceholder(v: string) {
    setInput((s) => s.replace(/\{tickers?\}/i, v));
    setTkQuery(""); setTkRes([]);
    inputRef.current?.focus();
  }

  const selected = agents.find((a) => a.id === agentId) || null;

  // apply one SSE event to the LAST (assistant) message — shared by live send + run resume.
  function applyEvent(ev: any) {
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
      else if (ev.type === "suggestions") a.suggestions = (ev.items || []) as string[];
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

  // Read an SSE body and apply events to the displayed assistant bubble. Generation lives
  // server-side, so if the user navigates to another conversation we just STOP rendering here
  // (the run keeps going); re-entering resumes it. `initialConv` is the conversation we expect
  // (null for a brand-new chat — learned from the first `run` event).
  async function consumeStream(body: ReadableStream<Uint8Array>, initialConv: string | null) {
    let myConv = initialConv;
    if (myConv) streamConvRef.current = myConv;
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    try {
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
          if (ev.type === "run") {  // first event: learn conversation id (new chats) + claim the stream
            myConv = ev.conversation_id || myConv;
            if (myConv) { setConversationId(myConv); streamConvRef.current = myConv; if (viewConvRef.current === null) viewConvRef.current = myConv; }
            continue;
          }
          // user moved to a different conversation → stop rendering (the run keeps generating server-side)
          if (myConv && viewConvRef.current !== myConv) { try { await reader.cancel(); } catch {} return; }
          if (ev.type === "conversation") { setConversationId(ev.id); continue; }
          applyEvent(ev);
        }
      }
    } finally {
      if (streamConvRef.current === myConv) streamConvRef.current = null;  // free it for a later re-tail
      if (viewConvRef.current === myConv) setBusy(false);                  // only if we're still here
    }
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    const history: Msg[] = [...messages, { role: "user", content: text }];
    const startConv = conversationId;  // may be null → a new conversation
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
          conversation_id: startConv,  // resume/append to the same conversation
        }),
      });
      if (!res.body) throw new Error("no stream");
      await consumeStream(res.body, startConv);
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], content: "(문제가 발생했어요. 잠시 후 다시 시도해 주세요.)" };
        return next;
      });
      setBusy(false);
    } finally {
      loadHistory();  // refresh the sidebar history (new conversation title shows up)
    }
  }

  // Resume a conversation whose answer is still generating server-side: append a live
  // assistant bubble and tail the background run (replays buffered events, then live).
  async function tailRun(convId: string, runId: string) {
    if (streamConvRef.current === convId) return;  // already streaming this one
    setBusy(true);
    setMessages((prev) => [...prev, { role: "assistant", content: "", tools: [], citations: [] }]);
    try {
      const res = await fetch(`/api/runs/${runId}/stream?from=0`);
      if (res.body) await consumeStream(res.body, convId);
      else setBusy(false);
    } catch { setBusy(false); }
    finally { loadHistory(); }
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
        <button className="rail-new" onClick={newChat}>
          <span className="ic">✎</span><span>새 대화</span>
        </button>
        <button className={`rail-item ${view === "desk" ? "on" : ""}`} onClick={() => setView("desk")}>
          <span className="ic">🏠</span><span className="lbl">데스크</span>
        </button>
        <button className={`rail-item ${view === "board" ? "on" : ""}`} onClick={() => setView("board")}>
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
        {convs.length > 0 && (
          <div className="rail-hist">
            <div className="rail-hist-h">최근 대화</div>
            {convs.slice(0, 12).map((c) => (
              <button key={c.id} className={`rail-conv ${c.id === conversationId ? "on" : ""}`}
                title={c.title} onClick={() => openConversation(c.id)}>{c.title || "(제목 없음)"}</button>
            ))}
          </div>
        )}
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
          <BoardCanvas onEvidence={setViewer} />
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
                  {libPrompts.length > 0 ? (
                    // prompt-library examples rising in an infinite loop; hover pauses; click
                    // drops the FULL prompt into the composer to fill {TICKER} and send.
                    <PromptWaterfall
                      prompts={libPrompts}
                      onPick={(body) => { setInput(body); inputRef.current?.focus(); }}
                    />
                  ) : (
                    <div className="examples">
                      {EXAMPLES.map((e) => (
                        <button key={e} className="chip" onClick={() => send(e)}>{e}</button>
                      ))}
                    </div>
                  )}
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
                    const used = evidenceOf(m);
                    const usedKeys = new Set(used.map((c) => `${c.source}|${c.url}`));
                    // every consulted source the answer DIDN'T directly cite (so nothing "disappears"
                    // when the answer finishes — the full sweep stays in its own section).
                    const others = cites.filter((c) => !usedKeys.has(`${c.source}|${c.url}`));
                    return (
                      <>
                        {used.length > 0 && (
                          <div className="answer-sources">
                            <div className="as-label">답변에 사용된 출처 {used.length}</div>
                            <div className="as-cards">
                              {used.map((c, j) => <SourceCard key={`u${j}`} c={c} onExpand={setViewer} onPin={pinCitation} />)}
                            </div>
                          </div>
                        )}
                        {others.length > 0 && (
                          <details className="answer-sources all-sources">
                            <summary className="as-label">참고한 모든 출처 {cites.length} · 답변 외 {others.length}</summary>
                            <div className="as-cards">
                              {others.map((c, j) => <SourceCard key={`o${j}`} c={c} onExpand={setViewer} onPin={pinCitation} />)}
                            </div>
                          </details>
                        )}
                        {(m.tools?.length || 0) > 0 && (
                          <details className="sources">
                            <summary>훑어본 도구 {uniqueTools(m.tools).length}개</summary>
                            {uniqueTools(m.tools).map((t, j) => <div key={`t${j}`} className="tool">🔧 {t.label || t.name}</div>)}
                          </details>
                        )}
                      </>
                    );
                  })()}
                  {m.role === "assistant" && (m.suggestions?.length || 0) > 0 && (
                    <div className="followups">
                      <div className="fu-label">이어서 더 파고들기</div>
                      <div className="fu-list">
                        {m.suggestions!.map((q, j) => (
                          <button key={j} type="button" className="fu-chip" disabled={busy} onClick={() => send(q)}>
                            {q} <span className="fu-arrow">→</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </main>

            <footer className="composer">
              {hasPlaceholder && (
                <div className="tickerfill">
                  <span className="tf-label">⌗ 종목 채우기</span>
                  {handles.slice(0, 6).map((h) => (
                    <button key={h} type="button" className="tf-chip group" onClick={() => fillPlaceholder("@" + h)}>@{h}</button>
                  ))}
                  <input className="tf-search" value={tkQuery} placeholder="종목 검색 (예: 삼성, AAPL)…"
                    onChange={(e) => searchTicker(e.target.value)} />
                  {tkRes.map((r, i) => (
                    <button key={`${r.ticker}${i}`} type="button" className="tf-chip" title={r.name}
                      onClick={() => fillPlaceholder(r.ticker)}>{r.ticker} · {(r.name || "").slice(0, 12)}</button>
                  ))}
                </div>
              )}
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
          categories={categories}
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
      {pinTarget && (
        <PinPicker spec={pinTarget} onClose={() => setPinTarget(null)} onPinned={() => setPinTarget(null)} />
      )}
    </div>
  );
}
