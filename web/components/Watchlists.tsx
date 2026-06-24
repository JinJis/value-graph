"use client";

// 관심 — wireframe 07. @그룹 = 탐색 호출 단위 + 알림 단위. Left: @group list with a bot indicator and an
// inline "＋ 새 그룹" (no always-on form); empty → recommended preset groups (one-tap, pre-filled).
// Right: group detail — bot banner (attach an alert to the whole group) + members table, each member
// linkable to its own alert. Attaching reuses the Alert Sheet (board-scope, target = @group/ticker).

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, ChannelStatus, channelMeta, targetLabel } from "@/lib/alerts";
import AlertSheet, { type AlertDraft } from "./AlertSheet";
import { Button, Chip, Mascot, Modal } from "./ui";

export type WatchItem = { id: string; market: string; ticker: string; name?: string | null };
export type Watchlist = { id: string; name: string; handle: string; count: number; items: WatchItem[] };
type SearchResult = { name?: string; ticker?: string; market?: string; cik?: string };

// Recommended starter groups (content, mirrors onboarding) — one tap creates a pre-filled @group.
const PRESETS: { id: string; name: string; items: { market: string; ticker: string; name?: string }[] }[] = [
  { id: "semi", name: "반도체", items: [
    { market: "KR", ticker: "005930.KS", name: "삼성전자" }, { market: "KR", ticker: "000660.KS", name: "SK하이닉스" },
    { market: "US", ticker: "NVDA", name: "NVIDIA" }, { market: "US", ticker: "TSM", name: "TSMC" }, { market: "US", ticker: "ASML", name: "ASML" }] },
  { id: "ai", name: "AI·빅테크", items: [
    { market: "US", ticker: "NVDA" }, { market: "US", ticker: "MSFT" }, { market: "US", ticker: "GOOGL" },
    { market: "US", ticker: "AAPL" }, { market: "US", ticker: "META" }, { market: "US", ticker: "AMZN" }] },
  { id: "energy", name: "에너지·원자재", items: [
    { market: "US", ticker: "XOM" }, { market: "US", ticker: "CVX" }, { market: "US", ticker: "COP" }, { market: "US", ticker: "SLB" }] },
  { id: "dividend", name: "배당·인컴", items: [
    { market: "US", ticker: "JNJ" }, { market: "US", ticker: "PG" }, { market: "US", ticker: "KO" }, { market: "US", ticker: "PEP" }] },
];

export default function Watchlists(
  { onClose, onChanged, embedded = false }:
  { onClose?: () => void; onChanged?: () => void; embedded?: boolean },
) {
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [channels, setChannels] = useState<ChannelStatus[]>([]);
  const [filter, setFilter] = useState("");           // left search: filter @groups
  const [creating, setCreating] = useState(false);     // inline ＋새 그룹 input visible
  const [newName, setNewName] = useState("");
  const [showSearch, setShowSearch] = useState(false); // ＋종목 reveals company search
  const [market, setMarket] = useState("US");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [alertDraft, setAlertDraft] = useState<AlertDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const active = lists.find((l) => l.id === activeId) || null;

  const load = useCallback(async (selectId?: string) => {
    try {
      const r = await fetch("/api/watchlists");
      if (r.ok) {
        const ls: Watchlist[] = (await r.json()).watchlists ?? [];
        setLists(ls);
        setActiveId((cur) => selectId ?? (ls.some((l) => l.id === cur) ? cur : ls[0]?.id ?? ""));
      }
    } catch {}
  }, []);
  const loadAlerts = useCallback(async () => {
    try { const r = await fetch("/api/alerts"); if (r.ok) setAlerts((await r.json()).alerts ?? []); } catch {}
  }, []);
  const loadChannels = useCallback(async () => {
    try { const r = await fetch("/api/channels"); if (r.ok) setChannels((await r.json()).channels ?? []); } catch {}
  }, []);
  useEffect(() => { load(); loadAlerts(); loadChannels(); }, [load, loadAlerts, loadChannels]);

  function changed() { load(activeId); onChanged?.(); }
  const botsFor = (name: string) => alerts.filter((a) => String(a.params?.target || "").replace(/^@/, "") === name);

  async function createGroup(name: string, items?: { market: string; ticker: string; name?: string }[]) {
    const nm = name.trim();
    if (!nm) return;
    setErr(""); setBusy(true);
    try {
      const r = await fetch("/api/watchlists", { method: "POST", body: JSON.stringify({ name: nm }) });
      if (!r.ok) { setErr((await r.json()).detail ?? "그룹을 만들 수 없습니다."); return; }
      const wl = await r.json();
      for (const it of items ?? []) {
        await fetch(`/api/watchlists/${wl.id}/items`, { method: "POST", body: JSON.stringify(it) }).catch(() => {});
      }
      setNewName(""); setCreating(false);
      await load(wl.id); onChanged?.();
    } finally { setBusy(false); }
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
  const inActive = (res: SearchResult) => !!active?.items.some((i) => i.market === res.market && i.ticker === res.ticker);
  async function favorite(res: SearchResult) {
    if (!active || !res.ticker) return;
    await fetch(`/api/watchlists/${active.id}/items`, { method: "POST", body: JSON.stringify({ market: res.market ?? market, ticker: res.ticker, name: res.name }) });
    changed();
  }
  async function removeItem(itemId: string) {
    if (!active) return;
    await fetch(`/api/watchlists/${active.id}/items/${itemId}`, { method: "DELETE" });
    changed();
  }
  function attachGroupAlert() {
    if (!active) return;
    setAlertDraft({ scope: "board", name: `${active.name} 알림`, params: { target: "@" + active.name },
      source_spec: { deeplink: `/?group=${encodeURIComponent(active.name)}` } });
  }
  function attachMemberAlert(it: WatchItem) {
    setAlertDraft({ scope: "board", name: `${it.name || it.ticker} 알림`, trigger_type: "earnings",
      params: { target: it.ticker }, source_spec: { deeplink: `/?ticker=${encodeURIComponent(it.ticker)}` } });
  }

  const visibleGroups = lists.filter((l) => !filter.trim() || l.name.toLowerCase().includes(filter.trim().toLowerCase()));
  const usedPreset = (p: { name: string }) => lists.some((l) => l.name === p.name);

  const body = (
    <>
      {err && <div className="err">{err}</div>}

      {lists.length === 0 ? (
        // empty → recommended preset groups (one-tap, pre-filled) + 직접 만들기
        <div className="wl-empty">
          <p className="muted-note">관심 그룹은 <b>@호출의 단위이자 알림의 단위</b>예요. 추천 그룹을 한 번에 담거나 직접 만드세요.</p>
          <div className="wl-presets">
            {PRESETS.map((p) => (
              <button key={p.id} type="button" className="wl-preset" disabled={busy} onClick={() => createGroup(p.name, p.items)}>
                <span className="wl-preset-n">@{p.name}</span>
                <span className="wl-preset-c">{p.items.length}종목 담기</span>
              </button>
            ))}
          </div>
          <div className="wl-new">
            <input className="input" placeholder="직접 만들기 — 그룹 이름 (예: 반도체바스켓)" value={newName}
              onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") createGroup(newName); }} />
            <Button onClick={() => createGroup(newName)} disabled={busy || !newName.trim()}>＋ 그룹</Button>
          </div>
        </div>
      ) : (
        <div className="wl-layout">
          {/* LEFT — @group list */}
          <div className="wl-groups">
            <input className="input wl-gsearch" placeholder="🔍 @그룹 검색" value={filter} onChange={(e) => setFilter(e.target.value)} />
            <div className="wl-glabel">@그룹</div>
            {visibleGroups.map((l) => {
              const bots = botsFor(l.name).length;
              return (
                <button key={l.id} type="button" className={`wl-group ${l.id === activeId ? "on" : ""}`} onClick={() => { setActiveId(l.id); setShowSearch(false); }}>
                  <span className="gh">@{l.name}</span>
                  <span className="gc">{l.count}</span>
                  <span className={`wl-botind ${bots ? "on" : ""}`} title={bots ? `봇 ${bots}개` : "봇 없음"}>{bots ? `🔔 ${bots}` : "봇 없음"}</span>
                </button>
              );
            })}
            {creating ? (
              <div className="wl-new">
                <input className="input" autoFocus placeholder="그룹 이름" value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") createGroup(newName); if (e.key === "Escape") { setCreating(false); setNewName(""); } }} />
                <Button size="sm" onClick={() => createGroup(newName)} disabled={busy || !newName.trim()}>추가</Button>
              </div>
            ) : (
              <button type="button" className="wl-addgroup" onClick={() => setCreating(true)}>＋ 새 그룹</button>
            )}
          </div>

          {/* RIGHT — group detail */}
          <div className="wl-detail">
            {active && (
              <>
                <div className="wl-dhead">
                  <div className="wl-dtitle"><b className="mono">@{active.name}</b><span className="wl-dsub">{active.count}개 종목 · @호출 단위</span></div>
                  <span className="grow" />
                  <Button variant="ghost" size="sm" onClick={() => setShowSearch((s) => !s)}>＋ 종목</Button>
                  <Button variant="ghost" size="sm" onClick={renameGroup}>이름 변경</Button>
                  <Button variant="danger" size="sm" onClick={deleteGroup}>삭제</Button>
                </div>

                {/* bot banner */}
                <div className="wl-botbanner">
                  <span className="wl-bot-ic">🔔</span>
                  <span className="wl-bot-txt">
                    {botsFor(active.name).length
                      ? <>이 그룹에 봇 {botsFor(active.name).length}개 — {botsFor(active.name).map((b) => b.trigger_label).join(" · ")} <span className="muted-note">→ 구성원 전체를 감시</span></>
                      : <>이 그룹에 붙은 봇이 없어요 — 실적·금리 알림을 붙이면 구성원 전체를 감시해요.</>}
                  </span>
                  <Button size="sm" onClick={attachGroupAlert}>＋ 알림 봇 붙이기</Button>
                </div>

                {showSearch && (
                  <div className="wl-searchbar">
                    <select className="wl-market" value={market} onChange={(e) => { setMarket(e.target.value); runSearch(query); }}>
                      <option value="US">US</option><option value="KR">KR</option>
                    </select>
                    <input className="input" placeholder="종목 검색 (이름 또는 티커)…" value={query} onChange={(e) => runSearch(e.target.value)} />
                  </div>
                )}
                {showSearch && results.length > 0 && (
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

                {/* members table: 종목 · 알림 */}
                <div className="wl-table">
                  <div className="wl-thead"><span>종목</span><span className="wl-th-alert">알림</span></div>
                  {active.items.length === 0 ? (
                    <p className="muted-note">담긴 종목이 없어요. <b>＋ 종목</b>으로 검색해 추가하세요.</p>
                  ) : active.items.map((it) => {
                    const memberBots = alerts.filter((a) => String(a.params?.target || "") === it.ticker);
                    return (
                      <div key={it.id} className="wl-trow">
                        <span className="wl-tname">{it.name || it.ticker} <span className="meta">{it.ticker} · {it.market}</span></span>
                        <span className="wl-talert">
                          {memberBots.length
                            ? memberBots.map((b) => <Chip key={b.id} tone="accent">{b.trigger_label}</Chip>)
                            : <button className="wl-addalert" onClick={() => attachMemberAlert(it)}>＋ 알림</button>}
                          <button className="star" title="그룹에서 제거" onClick={() => removeItem(it.id)}>✕</button>
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      )}
      <p className="disclaimer">그룹 이름은 탐색과 알림에서 <span className="mono">@핸들</span> 로 사용됩니다.</p>

      {alertDraft && (
        <AlertSheet initial={alertDraft} channels={channels}
          onClose={() => setAlertDraft(null)} onChannelsChanged={loadChannels}
          onCreated={() => { setAlertDraft(null); loadAlerts(); }} />
      )}
    </>
  );

  if (embedded) {
    return (
      <div className="embed">
        <div className="embed-head"><h3><Mascot /> 관심</h3></div>
        {body}
      </div>
    );
  }
  return <Modal title={<><Mascot /> 관심</>} wide onClose={() => onClose?.()}>{body}</Modal>;
}
