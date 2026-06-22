"use client";

import { useCallback, useEffect, useState } from "react";
import { ArtifactCard, type Artifact, fmtBig } from "./ArtifactCard";
import { Button } from "./ui";

type PF = { id: string; name: string; holdings: number };
type Position = {
  id: string; market: string; ticker: string; name?: string | null; shares: number;
  cost_basis?: number | null; price?: number | null; value?: number | null;
  weight?: number | null; gain?: number | null;
};
type Analytics = {
  id: string; name: string; positions: Position[]; total_value: number;
  total_cost?: number | null; total_gain?: number | null; backtest?: any; note?: string;
};

// CE-8: portfolio dashboard — manage holdings, see live value/allocation/unrealized gain, and a
// backtest equity curve. Descriptive only (no advice); prices flow through the gateway.
export default function PortfolioPanel({ onEvidence }: { onEvidence?: (c: any) => void }) {
  const [pfs, setPfs] = useState<PF[]>([]);
  const [active, setActive] = useState<string>("");
  const [data, setData] = useState<Analytics | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ market: "US", ticker: "", shares: "", cost_basis: "" });

  const loadPfs = useCallback(async () => {
    const r = await fetch("/api/portfolios");
    if (!r.ok) return;
    const list = ((await r.json()).portfolios ?? []) as PF[];
    setPfs(list);
    setActive((cur) => (cur && list.some((p) => p.id === cur) ? cur : list[0]?.id ?? ""));
  }, []);

  const loadAnalytics = useCallback(async (id: string) => {
    if (!id) { setData(null); return; }
    setBusy(true);
    try { const r = await fetch(`/api/portfolios/${id}/analytics`); if (r.ok) setData(await r.json()); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { loadPfs(); }, [loadPfs]);
  useEffect(() => { loadAnalytics(active); }, [active, loadAnalytics]);

  async function newPf() {
    const name = prompt("새 포트폴리오 이름");
    if (!name?.trim()) return;
    const r = await fetch("/api/portfolios", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    if (r.ok) { const p = await r.json(); await loadPfs(); setActive(p.id); }
  }
  async function deletePf() {
    if (!active || !confirm("이 포트폴리오를 삭제할까요?")) return;
    await fetch(`/api/portfolios/${active}`, { method: "DELETE" });
    setActive(""); await loadPfs();
  }
  async function addHolding() {
    if (!form.ticker.trim() || !active) return;
    await fetch(`/api/portfolios/${active}/holdings`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market: form.market, ticker: form.ticker.trim(),
        shares: parseFloat(form.shares) || 0, cost_basis: form.cost_basis ? parseFloat(form.cost_basis) : null }) });
    setForm({ market: form.market, ticker: "", shares: "", cost_basis: "" });
    loadAnalytics(active);
  }
  async function removeHolding(hid: string) {
    await fetch(`/api/portfolios/${active}/holdings/${hid}`, { method: "DELETE" });
    loadAnalytics(active);
  }

  const cur = (t?: string) => (/^\d/.test(t || "") ? "KRW" : "USD") as "KRW" | "USD";
  const curve: Artifact | null = data?.backtest?.curve?.length ? {
    kind: "timeseries", title: "포트폴리오 성과 (백테스트)", series: [
      { label: "포트폴리오", points: data.backtest.curve.map((p: any) => ({ x: p.date, y: p.value })) },
      ...(data.backtest.benchmark?.curve?.length ? [{ label: data.backtest.benchmark.ticker,
        points: data.backtest.benchmark.curve.map((p: any) => ({ x: p.date, y: p.value })) }] : []),
    ], source: "ingestion store",
  } : null;

  return (
    <div className="board">
      <div className="board-head">
        <h3>💼 포트폴리오</h3>
        <span className="sub">실시간 평가 · 비중 · 평가손익 · 백테스트 — 서술적(투자 조언 아님)</span>
      </div>
      <div className="board-tabs">
        {pfs.map((p) => (
          <button key={p.id} className={`board-tab ${p.id === active ? "on" : ""}`} onClick={() => setActive(p.id)}>
            {p.name} <span className="muted">· {p.holdings}</span>
          </button>
        ))}
        <button className="board-tab add" onClick={newPf} title="새 포트폴리오">＋</button>
        <span className="grow" />
        {active && <Button variant="ghost" size="sm" onClick={deletePf}>삭제</Button>}
      </div>

      {!active ? (
        <p className="live-empty">포트폴리오가 없어요. <b>＋</b>로 만들고 보유 종목을 추가하면 실시간 평가·비중·백테스트가 보여요.</p>
      ) : (
        <>
          <div className="pf-add">
            <select className="input" value={form.market} onChange={(e) => setForm({ ...form, market: e.target.value })}>
              <option value="US">US</option><option value="KR">KR</option>
            </select>
            <input className="input" placeholder="티커 (AAPL / 005930)" value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })} />
            <input className="input" placeholder="수량" value={form.shares}
              onChange={(e) => setForm({ ...form, shares: e.target.value })} />
            <input className="input" placeholder="평단가(선택)" value={form.cost_basis}
              onChange={(e) => setForm({ ...form, cost_basis: e.target.value })} />
            <Button onClick={addHolding} disabled={!form.ticker.trim()}>＋ 추가</Button>
          </div>

          {busy && !data ? <p className="live-empty">불러오는 중…</p> : data && (
            <>
              <div className="pf-summary">
                <div className="pf-stat"><span>총 평가액</span><b>{fmtBig(data.total_value, cur(data.positions[0]?.ticker))}</b></div>
                {data.total_gain != null && (
                  <div className="pf-stat"><span>평가손익</span>
                    <b className={data.total_gain >= 0 ? "up" : "down"}>{data.total_gain >= 0 ? "+" : ""}{fmtBig(data.total_gain, cur(data.positions[0]?.ticker))}</b></div>
                )}
              </div>

              {data.positions.length === 0 ? (
                <p className="live-empty">보유 종목을 추가해 보세요.</p>
              ) : (
                <table className="artifact-table kpi-table pf-table">
                  <thead><tr><th>종목</th><th className="mono">수량</th><th className="mono">현재가</th>
                    <th className="mono">평가액</th><th className="mono">비중</th><th className="mono">평가손익</th><th></th></tr></thead>
                  <tbody>
                    {data.positions.map((p) => (
                      <tr key={p.id}>
                        <td>{p.name || p.ticker}</td>
                        <td className="mono">{p.shares}</td>
                        <td className="mono">{p.price != null ? fmtBig(p.price, cur(p.ticker)) : "—"}</td>
                        <td className="mono">{p.value != null ? fmtBig(p.value, cur(p.ticker)) : "—"}</td>
                        <td className="mono">{p.weight != null ? `${(p.weight * 100).toFixed(1)}%` : "—"}</td>
                        <td className={`mono ${p.gain != null ? (p.gain >= 0 ? "up" : "down") : ""}`}>
                          {p.gain != null ? `${p.gain >= 0 ? "+" : ""}${fmtBig(p.gain, cur(p.ticker))}` : "—"}</td>
                        <td><button className="bc-btn" onClick={() => removeHolding(p.id)} title="제거">✕</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {curve && <div className="artifacts" style={{ marginTop: 14 }}><ArtifactCard a={curve} onEvidence={onEvidence} /></div>}
              {data.backtest?.note && <p className="live-empty">{data.backtest.note}</p>}
            </>
          )}
        </>
      )}
    </div>
  );
}
