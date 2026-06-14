"use client";

import { useEffect, useRef, useState } from "react";

export type WatchItem = { id: string; market: string; ticker: string; name?: string | null };
export type Watchlist = { id: string; name: string; handle: string; count: number; items: WatchItem[] };
type SearchResult = { name?: string; ticker?: string; market?: string; cik?: string };

/** 관심 — search any listed company, ⭐ it into a named @group. Groups are what
 *  the composer and the analyst builder tag with @handle. */
export default function Watchlists(
  { onClose, onChanged, embedded = false }:
  { onClose?: () => void; onChanged?: () => void; embedded?: boolean },
) {
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [market, setMarket] = useState("US");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [err, setErr] = useState("");
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const active = lists.find((l) => l.id === activeId) || null;

  async function load(selectId?: string) {
    try {
      const r = await fetch("/api/watchlists");
      if (r.ok) {
        const ls: Watchlist[] = (await r.json()).watchlists ?? [];
        setLists(ls);
        setActiveId((cur) => selectId ?? (ls.some((l) => l.id === cur) ? cur : ls[0]?.id ?? ""));
      }
    } catch {}
  }
  useEffect(() => { load(); }, []);

  function changed() { load(activeId); onChanged?.(); }

  async function createGroup() {
    const name = newName.trim();
    if (!name) return;
    setErr("");
    const r = await fetch("/api/watchlists", { method: "POST", body: JSON.stringify({ name }) });
    if (r.ok) { setNewName(""); const wl = await r.json(); await load(wl.id); onChanged?.(); }
    else setErr((await r.json()).detail ?? "그룹을 만들 수 없습니다.");
  }

  async function renameGroup() {
    if (!active) return;
    const name = prompt("그룹 이름 변경 (＝ @핸들)", active.name);
    if (!name || name === active.name) return;
    const r = await fetch(`/api/watchlists/${active.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
    if (r.ok) changed(); else setErr((await r.json()).detail ?? "이름을 바꿀 수 없습니다.");
  }

  async function deleteGroup() {
    if (!active || !confirm(`'${active.name}' 그룹을 삭제할까요?`)) return;
    await fetch(`/api/watchlists/${active.id}`, { method: "DELETE" });
    setActiveId(""); changed();
  }

  function runSearch(q: string) {
    setQuery(q);
    if (debounce.current) clearTimeout(debounce.current);
    if (!q.trim()) { setResults([]); return; }
    debounce.current = setTimeout(async () => {
      try {
        const r = await fetch(`/api/company/search?q=${encodeURIComponent(q)}&market=${market}`);
        if (r.ok) setResults((await r.json()).results ?? []);
      } catch {}
    }, 220);
  }

  const inActive = (res: SearchResult) =>
    !!active?.items.some((i) => i.market === res.market && i.ticker === res.ticker);

  async function favorite(res: SearchResult) {
    if (!active || !res.ticker) return;
    await fetch(`/api/watchlists/${active.id}/items`, {
      method: "POST",
      body: JSON.stringify({ market: res.market ?? market, ticker: res.ticker, name: res.name }),
    });
    changed();
  }

  async function removeItem(itemId: string) {
    if (!active) return;
    await fetch(`/api/watchlists/${active.id}/items/${itemId}`, { method: "DELETE" });
    changed();
  }

  const body = (
      <>
        {embedded ? (
          <div className="embed-head"><h3><span className="mascot" aria-hidden /> 관심 종목</h3></div>
        ) : (
          <div className="modal-head">
            <h3><span className="mascot" aria-hidden /> 관심 종목</h3>
            <button className="x" onClick={onClose}>✕</button>
          </div>
        )}
        {err && <div className="err">{err}</div>}

        <div className="newprompt" style={{ display: "flex", gap: 8 }}>
          <input className="input" placeholder="새 그룹 이름 (예: 반도체바스켓)" value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") createGroup(); }} />
          <button className="btn" onClick={createGroup} disabled={!newName.trim()}>＋ 그룹</button>
        </div>

        {lists.length === 0 ? (
          <p className="muted-note">아직 관심 그룹이 없어요. 그룹을 만들고 종목을 검색해 ⭐ 으로 담아보세요.</p>
        ) : (
          <div className="wl-layout">
            <div className="wl-groups">
              {lists.map((l) => (
                <div key={l.id} className={`wl-group ${l.id === activeId ? "on" : ""}`} onClick={() => setActiveId(l.id)}>
                  <span className="gh">@{l.name}</span>
                  <span className="gc">{l.count}</span>
                </div>
              ))}
            </div>

            <div className="wl-detail">
              {active && (
                <>
                  <div className="modal-foot">
                    <b className="mono">@{active.name}</b>
                    <span className="grow" />
                    <button className="btn ghost sm" onClick={renameGroup}>이름 변경</button>
                    <button className="btn danger sm" onClick={deleteGroup}>삭제</button>
                  </div>

                  <div className="wl-searchbar">
                    <select className="wl-market" value={market} onChange={(e) => { setMarket(e.target.value); runSearch(query); }}>
                      <option value="US">US</option>
                      <option value="KR">KR</option>
                    </select>
                    <input className="input" placeholder="종목 검색 (이름 또는 티커)…" value={query}
                      onChange={(e) => runSearch(e.target.value)} />
                  </div>

                  {results.length > 0 && (
                    <div className="wl-results">
                      {results.map((r) => (
                        <div key={`${r.market}-${r.ticker}`} className="wl-row">
                          <span>{r.name} <span className="meta">{r.ticker} · {r.market}</span></span>
                          <button className={`star ${inActive(r) ? "on" : ""}`} title={inActive(r) ? "이미 담김" : "관심에 추가"}
                            onClick={() => favorite(r)} disabled={inActive(r)}>{inActive(r) ? "★" : "☆"}</button>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="wl-items">
                    {active.items.length === 0 ? (
                      <p className="muted-note">담긴 종목이 없어요. 위에서 검색해 ⭐ 으로 추가하세요.</p>
                    ) : active.items.map((it) => (
                      <div key={it.id} className="wl-row">
                        <span>{it.name || it.ticker} <span className="meta">{it.ticker} · {it.market}</span></span>
                        <button className="star" title="제거" onClick={() => removeItem(it.id)}>✕</button>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
        <p className="disclaimer">그룹 이름은 채팅과 분석가 빌더에서 <span className="mono">@핸들</span> 로 사용됩니다.</p>
      </>
  );

  if (embedded) return <div className="embed">{body}</div>;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>{body}</div>
    </div>
  );
}
