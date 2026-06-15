"use client";

import { useState } from "react";

export type Agent = {
  id: string;
  name: string;
  description?: string | null;
  model: string;
  system_prompt?: string | null;
  data_sources: string[];
  is_template: boolean;
  editable: boolean;
};
export type Tool = { name: string; description?: string | null };
export type Connector = { id: string; name: string; description?: string | null; tools?: Tool[] };

// Builder modal: create a new agent, or edit/clone an existing one. Templates
// are read-only, so editing one starts a clone (new agent seeded from it).
export default function AgentBuilder({
  base,
  connectors,
  onClose,
  onSaved,
}: {
  base: Agent | null; // agent to edit/clone, or null for a blank new agent
  connectors: Connector[];
  onClose: () => void;
  onSaved: (a: Agent, deletedId?: string) => void;
}) {
  const cloning = !!base && !base.editable; // a template -> save as a new agent
  const [name, setName] = useState(base ? (cloning ? `${base.name} (복사본)` : base.name) : "");
  const [description, setDescription] = useState(base?.description ?? "");
  const [model, setModel] = useState(base?.model ?? "stub");
  const [systemPrompt, setSystemPrompt] = useState(base?.system_prompt ?? "");
  const [sources, setSources] = useState<string[]>(base?.data_sources ?? connectors.map((c) => c.id));
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const editing = !!base && base.editable; // existing own agent -> PATCH

  function toggle(id: string) {
    setSources((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  }

  async function save() {
    if (!name.trim()) {
      setErr("이름을 입력하세요.");
      return;
    }
    setBusy(true);
    setErr("");
    const body = { name, description, model, system_prompt: systemPrompt, data_sources: sources };
    try {
      const res = editing
        ? await fetch(`/api/agents/${base!.id}`, { method: "PATCH", body: JSON.stringify(body) })
        : await fetch("/api/agents", { method: "POST", body: JSON.stringify(body) });
      if (!res.ok) throw new Error(await res.text());
      onSaved(await res.json());
    } catch (e: any) {
      setErr("저장에 실패했어요. 다시 시도해 주세요.");
      setBusy(false);
    }
  }

  async function remove() {
    if (!editing) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/agents/${base!.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      onSaved(base!, base!.id);
    } catch {
      setErr("삭제에 실패했어요.");
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{editing ? "에이전트 편집" : cloning ? "에이전트 복제" : "새 에이전트"}</h3>
          <button className="x" onClick={onClose}>✕</button>
        </div>

        <label className="fld">
          <span>이름</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 공시 분석가" />
        </label>

        <label className="fld">
          <span>설명 (선택)</span>
          <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="이 에이전트가 무엇을 하나요?" />
        </label>

        <label className="fld">
          <span>모델</span>
          <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="stub">기본 (stub · 키 불필요)</option>
            <option value="gemini">Gemini (GOOGLE_API_KEY 필요)</option>
          </select>
        </label>

        <label className="fld">
          <span>시스템 프롬프트 (선택)</span>
          <textarea className="input ta" value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="에이전트의 역할·말투·규칙을 적어주세요." rows={3} />
        </label>

        <div className="fld">
          <span>데이터 소스 <span className="hint-inline">— 펼치면 안에 어떤 툴이 있는지 보여줘요</span></span>
          <div className="sources-list">
            {connectors.map((c) => {
              const tools = c.tools ?? [];
              const open = expanded.has(c.id);
              return (
                <div key={c.id} className={`src-row ${sources.includes(c.id) ? "on" : ""}`}>
                  <div className="src-head">
                    <label className="src-pick" title={c.description ?? ""}>
                      <input type="checkbox" checked={sources.includes(c.id)} onChange={() => toggle(c.id)} />
                      {c.name}
                    </label>
                    {tools.length > 0 && (
                      <button type="button" className="src-expand" aria-expanded={open}
                        onClick={() => toggleExpand(c.id)}>
                        {open ? "▾" : "▸"} 툴 {tools.length}
                      </button>
                    )}
                  </div>
                  {open && tools.length > 0 && (
                    <ul className="tool-list">
                      {tools.map((t) => (
                        <li key={t.name}>
                          <code className="tool-name">{t.name}</code>
                          {t.description ? <span className="tool-desc">{t.description}</span> : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
            {connectors.length === 0 && <div className="muted-note">데이터 소스를 불러오지 못했습니다.</div>}
          </div>
        </div>

        <div className="guard" style={{ marginBottom: 14 }}>🛡 매수/매도·목표가·전망은 자동 거절됩니다 (끌 수 없음)</div>

        {err && <div className="err">{err}</div>}

        <div className="modal-foot">
          {editing && (
            <button className="btn danger" onClick={remove} disabled={busy}>삭제</button>
          )}
          <div className="grow" />
          <button className="btn ghost" onClick={onClose} disabled={busy}>취소</button>
          <button className="btn" onClick={save} disabled={busy}>{busy ? "저장 중…" : "저장"}</button>
        </div>
      </div>
    </div>
  );
}
