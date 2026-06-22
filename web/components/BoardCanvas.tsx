"use client";

import { useCallback, useEffect, useState } from "react";
import { Rnd } from "react-rnd";
import { ArtifactCard, type Artifact } from "./ArtifactCard";
import { SourceCard, type Citation } from "./SourceCard";
import { Button } from "./ui";

type Board = { id: string; name: string };
type Item = { id: string; spec: any; x: number | null; y: number | null; w: number | null; h: number | null };

const DEF = { artifact: { w: 380, h: 320 }, source: { w: 300, h: 210 }, text: { w: 320, h: 160 } };

// Notion-like canvas: a user's pinned assets (charts, sources, text) freely placed, dragged,
// and resized; text blocks are editable. Several named boards, switchable by tab.
export default function BoardCanvas({ onEvidence }: { onEvidence?: (c: Citation) => void }) {
  const [boards, setBoards] = useState<Board[]>([]);
  const [active, setActive] = useState<string>("");
  const [items, setItems] = useState<Item[]>([]);

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
    if (r.ok) setItems((await r.json()).pinned ?? []);
  }, []);

  useEffect(() => { loadBoards(); }, [loadBoards]);
  useEffect(() => { if (active) loadItems(active); }, [active, loadItems]);

  async function saveLayout(id: string, patch: Partial<{ x: number; y: number; w: number; h: number }>) {
    await fetch(`/api/board/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
  }
  async function removeItem(id: string) {
    setItems((p) => p.filter((i) => i.id !== id));
    await fetch(`/api/board/${id}`, { method: "DELETE" });
  }
  async function refreshItem(id: string) {
    const r = await fetch(`/api/board/${id}/refresh`, { method: "POST" });
    if (r.ok) { const fresh = await r.json(); setItems((p) => p.map((i) => (i.id === id ? { ...i, spec: fresh.spec } : i))); }
  }
  async function saveText(id: string, text: string) {
    await fetch(`/api/board/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: { kind: "text", text } }) });
    setItems((p) => p.map((i) => (i.id === id ? { ...i, spec: { ...i.spec, text } } : i)));
  }
  async function addText() {
    const r = await fetch("/api/board", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: { kind: "text", text: "" }, board_ids: [active], x: 24, y: 24, w: DEF.text.w, h: DEF.text.h }) });
    if (r.ok) loadItems(active);
  }
  async function newBoard() {
    const name = prompt("새 보드 이름");
    if (!name?.trim()) return;
    const r = await fetch("/api/boards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    if (r.ok) { const b = await r.json(); await loadBoards(); setActive(b.id); }
  }
  async function renameBoard() {
    const cur = boards.find((b) => b.id === active);
    const name = prompt("보드 이름 변경", cur?.name ?? "");
    if (!name?.trim()) return;
    await fetch(`/api/boards/${active}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    loadBoards();
  }
  async function deleteBoard() {
    if (!confirm("이 보드와 안의 카드를 모두 삭제할까요?")) return;
    await fetch(`/api/boards/${active}`, { method: "DELETE" });
    setActive("");
    await loadBoards();
  }

  return (
    <div className="board">
      <div className="board-head">
        <h3>📊 보드</h3>
        <span className="sub">노션처럼 — 끌어서 배치 · 모서리로 크기 조절 · 메모 작성</span>
      </div>

      <div className="board-tabs">
        {boards.map((b) => (
          <button key={b.id} className={`board-tab ${b.id === active ? "on" : ""}`} onClick={() => setActive(b.id)}>{b.name}</button>
        ))}
        <button className="board-tab add" onClick={newBoard} title="새 보드">＋</button>
        <span className="grow" />
        {active && <>
          <Button variant="ghost" size="sm" onClick={addText}>＋ 메모</Button>
          <Button variant="ghost" size="sm" onClick={renameBoard}>이름변경</Button>
          <Button variant="ghost" size="sm" onClick={deleteBoard}>보드삭제</Button>
        </>}
      </div>

      {items.length === 0 ? (
        <p className="live-empty">이 보드는 비어 있어요. 답변의 차트·표·<b>출처</b> 카드에서 <b>📌</b>를 누르면 여기에 모이고, <b>＋ 메모</b>로 글을 적어 자유롭게 배치할 수 있어요.</p>
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
                  x: Math.round(p.x), y: Math.round(p.y),
                  w: Math.round(ref.offsetWidth), h: Math.round(ref.offsetHeight) }); }}>
                <div className="bc-card">
                  <div className="bc-drag">
                    <span className="bc-grip">⠿</span>
                    <span className="bc-title">{it.spec?.title || (kind === "text" ? "메모" : "카드")}</span>
                    <span className="grow" />
                    {kind === "artifact" && it.spec?.tool && (
                      <button className="bc-btn" title="새로고침" onClick={() => refreshItem(it.id)}>↻</button>
                    )}
                    <button className="bc-btn" title="삭제" onClick={() => removeItem(it.id)}>✕</button>
                  </div>
                  <div className="bc-body">
                    {kind === "artifact" && <ArtifactCard a={it.spec as Artifact} onEvidence={onEvidence} />}
                    {kind === "source" && <SourceCard c={it.spec as Citation} onExpand={onEvidence} />}
                    {kind === "text" && (
                      <textarea className="bc-text" defaultValue={it.spec?.text ?? ""}
                        placeholder="여기에 분석 메모를 적어보세요…"
                        onBlur={(e) => saveText(it.id, e.target.value)} />
                    )}
                  </div>
                </div>
              </Rnd>
            );
          })}
        </div>
      )}
    </div>
  );
}
