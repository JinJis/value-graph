"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Rnd } from "react-rnd";
import { ArtifactCard, type Artifact } from "./ArtifactCard";
import { SourceCard, type Citation } from "./SourceCard";
import AlertSheet, { type AlertDraft } from "./AlertSheet";
import WidgetGallery, { type AddedWidget } from "./WidgetGallery";
import { Button } from "./ui";
import { ChannelStatus, TriggerType } from "@/lib/alerts";

type Board = { id: string; name: string };
type Item = { id: string; spec: any; x: number | null; y: number | null; w: number | null; h: number | null };
type Template = { id: string; name: string; description?: string; market?: string | null; widgets: any[] };

const DEF = { artifact: { w: 380, h: 320 }, source: { w: 300, h: 210 }, text: { w: 320, h: 160 } };
const RANGES = ["1D", "1W", "1M", "1Y", "LIVE"];

// Guess a widget's natural alert trigger from its data source, so the widget-bell opens the sheet
// pre-set sensibly (the user can still change it).
function triggerForSpec(spec: any): TriggerType {
  const s = `${spec?.tool || ""} ${spec?.source || ""}`.toLowerCase();
  if (/fred|ecos|bls|cpi|macro/.test(s)) return "macro_indicator";
  if (/news/.test(s) || spec?.kind === "feed") return "filing_news";
  if (/dart|sec|edgar|financ|income/.test(s)) return "earnings";
  if (/price|yahoo|kis/.test(s)) return "price_threshold";
  return "digest";
}

function TextBlock({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <textarea className="bc-text" autoFocus defaultValue={value}
        placeholder="마크다운으로 메모… ( ## 제목 · **굵게** · - 목록 · [링크](url) )"
        onMouseDown={(e) => e.stopPropagation()}
        onBlur={(e) => { setEditing(false); onSave(e.target.value); }} />
    );
  }
  return (
    <div className="bc-md md" onClick={() => setEditing(true)} title="클릭해 편집">
      {value ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown> : <span className="bc-ph">클릭해 메모 작성 (마크다운 지원)</span>}
    </div>
  );
}

function InlineEdit({ value, placeholder, onSave, className }: {
  value: string; placeholder: string; onSave: (v: string) => void; className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value);
  useEffect(() => { setV(value); }, [value]);
  if (editing) {
    return (
      <input className={`bc-edit ${className || ""}`} autoFocus value={v}
        onChange={(e) => setV(e.target.value)}
        onMouseDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}
        onBlur={() => { setEditing(false); if (v !== value) onSave(v); }}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setV(value); setEditing(false); } }} />
    );
  }
  return (
    <span className={`bc-editable ${className || ""}`} title="클릭해 수정"
      onClick={(e) => { e.stopPropagation(); setEditing(true); }}>
      {value || <span className="bc-ph">{placeholder}</span>}
    </span>
  );
}

// The dashboard (홈): a board's pinned WIDGETS on a free grid — dragged, resized, refreshed; every
// widget carries source · as_of · freshness, and a 🔔 to set a per-widget alert. Empty boards offer
// the template gallery (F2). ＋위젯 opens the all-sources gallery (F4); the board-bell sets a
// board-scope alert. Several named dashboards switchable by tab.
export default function BoardCanvas({ onEvidence }: { onEvidence?: (c: Citation) => void }) {
  const [boards, setBoards] = useState<Board[]>([]);
  const [active, setActive] = useState<string>("");
  const [items, setItems] = useState<Item[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [channels, setChannels] = useState<ChannelStatus[]>([]);
  const [range, setRange] = useState("1M");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [gallery, setGallery] = useState(false);
  const [applying, setApplying] = useState(false);  // guards template apply against double-click
  const [alertDraft, setAlertDraft] = useState<AlertDraft | null>(null);
  const itemsRef = useRef<Item[]>([]);
  itemsRef.current = items;
  const populatedRef = useRef<Set<string>>(new Set());  // tool widgets we've auto-refreshed once

  const loadBoards = useCallback(async () => {
    const r = await fetch("/api/boards");
    if (!r.ok) return;
    const bs = ((await r.json()).boards ?? []) as Board[];
    setBoards(bs);
    setActive((cur) => (cur && bs.some((b) => b.id === cur) ? cur : bs[0]?.id ?? ""));
  }, []);
  const loadItems = useCallback(async (bid: string) => {
    if (!bid) return;
    const r = await fetch(`/api/board?board_id=${encodeURIComponent(bid)}`);
    if (r.ok) {
      const pinned = ((await r.json()).pinned ?? []) as Item[];
      const seen = new Set<string>();
      setItems(pinned.filter((p) => (seen.has(p.id) ? false : seen.add(p.id))));  // defensive de-dup by id
      setLastRefresh(new Date().toLocaleTimeString());
    }
  }, []);
  const loadChannels = useCallback(async () => {
    try { const r = await fetch("/api/channels"); if (r.ok) setChannels((await r.json()).channels ?? []); } catch {}
  }, []);

  useEffect(() => { loadBoards(); loadChannels(); }, [loadBoards, loadChannels]);
  useEffect(() => { if (active) loadItems(active); }, [active, loadItems]);
  useEffect(() => {
    if (items.length === 0 && templates.length === 0) {
      fetch("/api/templates").then((r) => (r.ok ? r.json() : { templates: [] })).then((d) => setTemplates(d.templates ?? [])).catch(() => {});
    }
  }, [items.length, templates.length]);

  async function saveLayout(id: string, patch: Partial<{ x: number; y: number; w: number; h: number }>) {
    await fetch(`/api/board/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
  }
  async function removeItem(id: string) {
    setItems((p) => p.filter((i) => i.id !== id));
    await fetch(`/api/board/${id}`, { method: "DELETE" });
  }
  const refreshItem = useCallback(async (id: string) => {
    const r = await fetch(`/api/board/${id}/refresh`, { method: "POST" });
    if (r.ok) { const fresh = await r.json(); setItems((p) => p.map((i) => (i.id === id ? { ...i, spec: fresh.spec } : i))); }
  }, []);
  async function refreshAll() {
    setLastRefresh(new Date().toLocaleTimeString());
    await Promise.allSettled(itemsRef.current.filter((i) => i.spec?.tool).map((i) => refreshItem(i.id)));
  }
  // auto-refresh: every 30s re-fetch tool-bearing widgets (LIVE dashboard).
  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => { void refreshAll(); }, 30_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh]);
  // Populate freshly added / templated tool widgets that have no data yet — once each, so a
  // template-applied or post-onboarding dashboard fills in (failed refresh stays an honest gap).
  useEffect(() => {
    const dataless = items.filter((it) => it.spec?.tool && !populatedRef.current.has(it.id)
      && !(it.spec?.series?.length || it.spec?.candles?.length || it.spec?.table?.length || it.spec?.sections?.length));
    if (!dataless.length) return;
    dataless.forEach((it) => populatedRef.current.add(it.id));
    void Promise.allSettled(dataless.map((it) => refreshItem(it.id)));
  }, [items, refreshItem]);

  async function saveSpec(id: string, patch: Record<string, any>) {
    let merged: any = null;
    setItems((p) => p.map((i) => { if (i.id !== id) return i; merged = { ...i.spec, ...patch }; return { ...i, spec: merged }; }));
    if (merged) await fetch(`/api/board/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: merged }) });
  }
  async function addText() {
    const r = await fetch("/api/board", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: { kind: "text", text: "" }, board_ids: [active], x: 24, y: 24, w: DEF.text.w, h: DEF.text.h }) });
    if (r.ok) loadItems(active);
  }
  async function newBoard() {
    const name = prompt("새 대시보드 이름");
    if (!name?.trim()) return;
    const r = await fetch("/api/boards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    if (r.ok) { const b = await r.json(); await loadBoards(); setActive(b.id); }
  }
  async function renameBoard() {
    const cur = boards.find((b) => b.id === active);
    const name = prompt("대시보드 이름 변경", cur?.name ?? "");
    if (!name?.trim()) return;
    await fetch(`/api/boards/${active}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    loadBoards();
  }
  async function deleteBoard() {
    if (!confirm("이 대시보드와 위젯을 모두 삭제할까요?")) return;
    await fetch(`/api/boards/${active}`, { method: "DELETE" });
    setActive(""); await loadBoards();
  }
  async function applyTemplate(tid: string) {
    if (applying) return;  // guard against double-click → duplicate widgets
    setApplying(true);
    try {
      let bid = active;
      if (!bid) { await newBoard(); bid = active; }
      const r = await fetch("/api/board/from-template", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template_id: tid, board_id: bid || undefined }) });
      if (r.ok) { const d = await r.json(); setActive(d.board_id); await loadItems(d.board_id); await refreshAll(); }
    } finally { setApplying(false); }
  }
  function openBoardAlert() {
    setAlertDraft({ scope: "board", board_id: active, source_spec: { deeplink: `/?board=${active}` } });
  }
  function openWidgetAlert(it: Item) {
    const target = it.spec?.args?.ticker || it.spec?.ticker || it.spec?.title;
    setAlertDraft({
      scope: "widget", board_id: active, pin_id: it.id, name: it.spec?.title,
      trigger_type: triggerForSpec(it.spec), params: { target },
      source_spec: { tool: it.spec?.tool, args: it.spec?.args, source: it.spec?.source, deeplink: `/?board=${active}&widget=${it.id}` },
    });
  }
  function onWidgetAdded(w: AddedWidget) {
    setGallery(false);
    loadItems(active);
    if (w.withAlert && w.pinId) {
      setAlertDraft({
        scope: "widget", board_id: active, pin_id: w.pinId, name: w.spec?.title,
        trigger_type: triggerForSpec(w.spec), params: { target: w.spec?.args?.ticker || w.spec?.title },
        source_spec: { tool: w.spec?.tool, args: w.spec?.args, source: w.spec?.source, deeplink: `/?board=${active}&widget=${w.pinId}` },
      });
    }
  }

  const activeBoard = boards.find((b) => b.id === active);

  return (
    <div className="board">
      {/* top control bar (wireframe 03) */}
      <div className="dash-tabs">
        {boards.map((b) => (
          <button key={b.id} className={`board-tab ${b.id === active ? "on" : ""}`} onClick={() => setActive(b.id)}>{b.name}</button>
        ))}
        <button className="board-tab add" onClick={newBoard} title="새 대시보드">＋ 대시보드</button>
      </div>

      <div className="dash-bar">
        <div className="dash-range">
          {RANGES.map((r) => (
            <button key={r} className={`dash-range-btn ${range === r ? "on" : ""}`} onClick={() => setRange(r)}>
              {r === "LIVE" ? <><span className="fdot fresh" /> LIVE</> : r}
            </button>
          ))}
        </div>
        <button className={`dash-auto ${autoRefresh ? "on" : ""}`} onClick={() => setAutoRefresh((v) => !v)}
          title={autoRefresh ? "자동갱신 켜짐 (30s)" : "자동갱신 꺼짐 — 켜기"}>↻ 30s</button>
        <button className="dash-chip" onClick={() => void refreshAll()} title="지금 전체 갱신">↻ 갱신</button>
        <span className="grow" />
        {active && (
          <>
            <button className="dash-bell" onClick={openBoardAlert} title="이 보드 전체 알림">🔔 보드 알림</button>
            <Button variant="ghost" size="sm" onClick={() => alert("공유 링크는 곧 제공됩니다.")}>↗ 공유</Button>
            <Button size="sm" onClick={() => setGallery(true)}>＋ 위젯</Button>
          </>
        )}
      </div>

      {active && (
        <div className="dash-meta">
          <span className="fdot fresh" /> 실시간 · 마지막 갱신 {lastRefresh ?? "—"} · {items.length}개 위젯
          <span className="grow" />
          <button className="dash-link" onClick={addText}>＋ 메모</button>
          <button className="dash-link" onClick={renameBoard}>이름변경</button>
          <button className="dash-link" onClick={deleteBoard}>삭제</button>
        </div>
      )}

      {items.length === 0 ? (
        // empty state → template gallery (wireframe 02)
        <div className="dash-empty">
          <div className="dash-hero">
            <h2>나만의 실시간 대시보드를 시작하세요</h2>
            <p>템플릿으로 바로 채우거나, <b>탐색</b>에서 자연어로 찾아 위젯을 추가하세요.</p>
          </div>
          <div className="tpl-grid">
            {templates.map((t) => (
              <button key={t.id} type="button" className="tpl-card" disabled={applying} onClick={() => applyTemplate(t.id)}>
                <div className="tpl-prev"><span /><span /><span /><span /></div>
                <div className="tpl-name">{t.name}</div>
                <div className="tpl-desc">{t.description}</div>
                <div className="tpl-cta">{applying ? "추가 중…" : "이 템플릿으로 시작 →"}</div>
              </button>
            ))}
            <button type="button" className="tpl-card blank" onClick={() => setGallery(true)}>
              <div className="tpl-blank-ic">＋</div>
              <div className="tpl-name">빈 캔버스로</div>
              <div className="tpl-desc">위젯을 직접 추가</div>
            </button>
          </div>
        </div>
      ) : (
        <div className="board-canvas">
          {items.map((it, idx) => {
            const kind = it.spec?.kind === "source" ? "source" : it.spec?.kind === "text" ? "text" : "artifact";
            const d = DEF[kind];
            const x = it.x ?? 24 + (idx % 3) * (d.w + 20);
            const y = it.y ?? 24 + Math.floor(idx / 3) * (d.h + 20);
            return (
              <Rnd key={`${active}:${it.id}`} bounds="parent" dragHandleClassName="bc-drag"
                default={{ x, y, width: it.w ?? d.w, height: it.h ?? d.h }}
                minWidth={200} minHeight={110} className="bc-item"
                onDragStop={(_e, p) => { void saveLayout(it.id, { x: Math.round(p.x), y: Math.round(p.y) }); }}
                onResizeStop={(_e, _dir, ref, _delta, p) => { void saveLayout(it.id, {
                  x: Math.round(p.x), y: Math.round(p.y), w: Math.round(ref.offsetWidth), h: Math.round(ref.offsetHeight) }); }}>
                <div className="bc-card">
                  <div className="bc-drag">
                    <span className="bc-grip">⠿</span>
                    <InlineEdit className="bc-title" value={it.spec?.title || ""}
                      placeholder={kind === "text" ? "메모 제목" : "제목"} onSave={(v) => saveSpec(it.id, { title: v })} />
                    <span className="grow" />
                    {kind !== "text" && (
                      <button className="bc-btn" title="이 위젯에 알림" onClick={() => openWidgetAlert(it)}>🔔</button>
                    )}
                    {kind === "artifact" && it.spec?.tool && (
                      <button className="bc-btn" title="새로고침" onClick={() => refreshItem(it.id)}>↻</button>
                    )}
                    <button className="bc-btn" title="삭제" onClick={() => removeItem(it.id)}>✕</button>
                  </div>
                  <div className="bc-body">
                    {/* hideTitle: the board card header already shows the title — avoid the duplicate */}
                    {kind === "artifact" && <ArtifactCard a={it.spec as Artifact} onEvidence={onEvidence} hideTitle />}
                    {kind === "source" && <SourceCard c={it.spec as Citation} onExpand={onEvidence} hideTitle />}
                    {kind === "text" && <TextBlock value={it.spec?.text ?? ""} onSave={(v) => saveSpec(it.id, { text: v })} />}
                  </div>
                </div>
              </Rnd>
            );
          })}
        </div>
      )}

      {gallery && active && (
        <WidgetGallery boardId={active} boardName={activeBoard?.name} onClose={() => setGallery(false)} onAdded={onWidgetAdded} />
      )}
      {alertDraft && (
        <AlertSheet initial={alertDraft} channels={channels} boardName={activeBoard?.name}
          widgetName={alertDraft.scope === "widget" ? alertDraft.name : undefined}
          onClose={() => setAlertDraft(null)} onChannelsChanged={loadChannels}
          onCreated={() => setAlertDraft(null)} />
      )}
    </div>
  );
}
