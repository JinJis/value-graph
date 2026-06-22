"use client";

import { useEffect, useState } from "react";
import { FreshnessDot } from "./ui";
import { TradeChart } from "./TradeChart";
import type { Citation } from "./SourceCard";

// U3-02 / PH-VIZ-1: render a connector-backed Artifact as an interactive card. Time-series
// and price (candlestick) artifacts delegate to <TradeChart> (TradingView Lightweight
// Charts); a 차트/표 toggle keeps the extracted-figures table; KPI/table artifacts render
// as a sourced matrix.

type ArtifactPoint = { x: string; y: number | null };
type ArtifactSeries = { label: string; unit?: string | null; points: ArtifactPoint[] };
type ArtifactCandle = {
  time: string; open?: number | null; high?: number | null; low?: number | null;
  close?: number | null; volume?: number | null;
};
export type ArtifactMarker = {
  time: string; label: string; kind?: string; position?: string;
  color?: string | null; source?: string | null; url?: string | null; snippet?: string | null;
};
export type ArtifactPriceLine = { price: number; label: string; color?: string | null };
export type ChartAnnotations = {
  lines?: { x1: string; y1: number; x2: string; y2: number; label?: string | null; color?: string | null }[];
  hlines?: { price: number; label?: string | null; color?: string | null }[];
  vlines?: { time: string; label?: string | null; color?: string | null }[];
  zones?: { t0: string; t1: string; label?: string | null; color?: string | null }[];
  rebase?: boolean;
  note?: string | null;
};
export type OverlayLine = {
  label: string; color?: string | null; points: { time: string; value: number }[];
};
export type ChartOverlay = {
  key: string; name: string; pane?: string; unit?: string | null;
  lines: OverlayLine[]; source?: string | null;
};
export type Artifact = {
  kind: string;
  title: string;
  series: ArtifactSeries[];
  candles?: ArtifactCandle[];  // kind=candlestick (prices): real OHLCV → candles + volume
  markers?: ArtifactMarker[];  // PH-VIZ-2: sourced events on the time axis (click → evidence)
  pricelines?: ArtifactPriceLine[];  // PH-VIZ-2: descriptive period high/low lines
  annotations?: ChartAnnotations | null;  // PH-VIZ-3: agent-authored lines/levels/zones
  user_annotations?: ChartAnnotations | null;  // PH-VIZ-5: the user's own drawings (persisted on pin)
  overlays?: ChartOverlay[];   // PH-VIZ-4: technical indicators (price-pane + sub-panes)
  table?: string[][] | null;   // kind in {table, kpi}: header-first matrix (each row sourced)
  source?: string | null;
  as_of?: string | null;
  freshness?: string | null;
  ticker?: string | null;
  has_gap?: boolean;
  tool?: string | null;
  args?: ({ market?: string } & Record<string, unknown>) | null;  // tool args (for re-fetch / market)
};

const STROKES = ["#5A5A62", "#A6A6AC", "#1FA463", "#D9A300"]; // table-view legend swatches

// PH-DATA-5: a table/KPI artifact (no time series) — render the header-first matrix as a
// card so a pinned KPI card shows on the Board too. Pin/remove reuse the chart-card chrome.
function TableArtifact(
  { a, onPin, onRemove }: { a: Artifact; onPin?: (spec: Artifact) => void; onRemove?: () => void },
) {
  const [pinned, setPinned] = useState(false);
  const t = a.table ?? [];
  const [head, ...rows] = t;
  if (!head || rows.length === 0) return null;
  return (
    <div className="artifact kpi-card">
      <div className="artifact-head">
        <span className="artifact-title">{a.title}</span>
        <FreshnessDot f={a.freshness ?? undefined} />
        <span className="grow" />
        {onPin && (
          <button type="button" className="artifact-toggle" disabled={pinned}
            onClick={() => { onPin(a); setPinned(true); }}>{pinned ? "📌 핀됨" : "📌 핀"}</button>
        )}
        {onRemove && (
          <button type="button" className="artifact-toggle" onClick={onRemove} title="보드에서 제거">✕</button>
        )}
      </div>
      <table className="artifact-table kpi-table">
        <thead><tr>{head.map((h, i) => <th key={i} className={i === 0 ? "" : "mono"}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri}>{r.map((cell, ci) => <td key={ci} className={ci === 0 ? "" : "mono"}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
      <div className="artifact-foot">
        <span className="artifact-src">
          {a.source || "출처"}{a.as_of ? <span className="mono"> · as of {a.as_of}</span> : null}
          <span className="kpi-evlabel"> · 각 수치는 공시 원문에 인용</span>
        </span>
      </div>
    </div>
  );
}

function fmt(y: number | null | undefined, unit?: string | null) {
  if (y == null) return "—";
  if (unit === "ratio") return (y * 100).toFixed(1) + "%";
  const abs = Math.abs(y);
  if (abs >= 1e12) return (y / 1e12).toFixed(2) + "T";
  if (abs >= 1e9) return (y / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return (y / 1e6).toFixed(2) + "M";
  return y.toLocaleString();
}

export function ArtifactCard(
  { a, onPin, onRemove, onRefresh, onEvidence, onAnnotate }:
  { a: Artifact; onPin?: (spec: Artifact) => void; onRemove?: () => void; onRefresh?: () => Promise<void> | void;
    onEvidence?: (c: Citation) => void;
    // PH-VIZ-5: persist the user's drawings (provided for already-pinned Board cards).
    onAnnotate?: (ann: ChartAnnotations | null) => void },
) {
  const [table, setTable] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [busy, setBusy] = useState(false);
  // PH-VIZ-5: the user's drawings — seeded from the spec so a pinned chart keeps them.
  const [userAnn, setUserAnn] = useState<ChartAnnotations | null>(a.user_annotations ?? null);
  const draw = (next: ChartAnnotations | null) => { setUserAnn(next); onAnnotate?.(next); };
  // Load a GENEROUS price history independently of the agent's narrow fetch, so range buttons
  // + scrolling show real data and the table is full OHLCV (not just the close window).
  const [bars, setBars] = useState<ArtifactCandle[] | null>(null);
  const ticker = a.ticker || "";
  useEffect(() => {
    if (!ticker || (a.candles?.length ?? 0) === 0) return;  // only for price (candlestick) charts
    const market = (a.args?.market as string) || (/^\d/.test(ticker) ? "KR" : "US");
    const end = new Date().toISOString().slice(0, 10);
    const start = `${new Date().getUTCFullYear() - 8}-01-01`;  // ~8y back covers 1Y/5Y + scrolling
    let cancel = false;
    (async () => {
      try {
        const q = `ticker=${encodeURIComponent(ticker)}&market=${market}&interval=day&start_date=${start}&end_date=${end}`;
        const r = await fetch(`/api/prices?${q}`);
        if (!r.ok) return;
        const d = await r.json();
        const rows: ArtifactCandle[] = (d.prices || [])
          .filter((p: any) => p?.time)
          .map((p: any) => ({ time: String(p.time).slice(0, 10), open: p.open, high: p.high, low: p.low, close: p.close, volume: p.volume }));
        if (!cancel && rows.length) setBars(rows);
      } catch { /* keep the agent's candles on failure */ }
    })();
    return () => { cancel = true; };
  }, [ticker, a.args]);
  // a KPI / table artifact carries a matrix instead of time series — render that shape.
  if ((a.kind === "kpi" || a.kind === "table" || a.series.length === 0) && a.table?.length) {
    return <TableArtifact a={a} onPin={onPin} onRemove={onRemove} />;
  }
  const xs = Array.from(new Set(a.series.flatMap((s) => s.points.map((p) => p.x)))).sort();
  const hasCandles = (a.candles?.length ?? 0) > 0;
  const hasOverlays = (a.overlays?.length ?? 0) > 0;  // PH-VIZ-4: technical-only chart
  if (xs.length === 0 && !hasCandles && !hasOverlays) return null;

  return (
    <div className="artifact">
      <div className="artifact-head">
        <span className="artifact-title">{a.title}</span>
        <FreshnessDot f={a.freshness ?? undefined} />
        {a.series.length > 0 && (
          <button type="button" className="artifact-toggle" onClick={() => setTable((t) => !t)}>
            {table ? "📈 차트" : "⇄ 표로"}
          </button>
        )}
        {onRefresh && (
          <button type="button" className="artifact-toggle" disabled={busy}
            onClick={async () => { setBusy(true); try { await onRefresh(); } finally { setBusy(false); } }}>
            {busy ? "…" : "↻ 새로고침"}
          </button>
        )}
        {onPin && (
          <button type="button" className="artifact-toggle" disabled={pinned}
            onClick={() => { onPin({ ...a, user_annotations: userAnn ?? undefined }); setPinned(true); }}>
            {pinned ? "📌 핀됨" : "📌 핀"}
          </button>
        )}
        {onRemove && (
          <button type="button" className="artifact-toggle" onClick={onRemove} title="보드에서 제거">✕</button>
        )}
      </div>

      {table ? (
        hasCandles ? (
          // OHLCV table (the chart is candlestick) — newest first, full history from /api/prices
          <table className="artifact-table">
            <thead><tr><th>날짜</th><th>시가</th><th>고가</th><th>저가</th><th>종가</th><th>거래량</th></tr></thead>
            <tbody>
              {[...(bars ?? a.candles ?? [])].reverse().slice(0, 260).map((c) => (
                <tr key={c.time}>
                  <td className="mono">{c.time}</td>
                  <td className="mono">{fmt(c.open)}</td>
                  <td className="mono">{fmt(c.high)}</td>
                  <td className="mono">{fmt(c.low)}</td>
                  <td className="mono">{fmt(c.close)}</td>
                  <td className="mono">{fmt(c.volume)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="artifact-table">
            <thead><tr><th>기간</th>{a.series.map((s) => <th key={s.label}>{s.label}</th>)}</tr></thead>
            <tbody>
              {xs.map((x) => (
                <tr key={x}>
                  <td className="mono">{x}</td>
                  {a.series.map((s) => {
                    const pt = s.points.find((p) => p.x === x);
                    return <td key={s.label} className="mono">{fmt(pt?.y, s.unit)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : (
        <TradeChart a={a} bars={bars} onEvidence={onEvidence} userAnn={userAnn} onDraw={draw} />
      )}

      <div className="artifact-foot">
        {!hasCandles && a.series.length > 0 && (
          <div className="artifact-legend">
            {a.series.map((s, i) => (
              <span key={s.label}><i style={{ background: STROKES[i % STROKES.length] }} /> {s.label}</span>
            ))}
          </div>
        )}
        {hasOverlays && (
          <div className="artifact-legend">
            {(a.overlays ?? []).flatMap((o) => o.lines).map((l) => (
              <span key={l.label}><i style={{ background: l.color ?? "#86868C" }} /> {l.label}</span>
            ))}
          </div>
        )}
        <span className="artifact-src">
          {a.source || "출처"}{a.as_of ? <span className="mono"> · as of {a.as_of}</span> : null}
          {a.has_gap ? <span className="artifact-gap"> · 일부 구간 공백</span> : null}
        </span>
      </div>
    </div>
  );
}
