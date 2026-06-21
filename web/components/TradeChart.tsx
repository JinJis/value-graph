"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { Artifact, ArtifactMarker } from "./ArtifactCard";
import type { Citation } from "./SourceCard";

const MARKER_SHAPE: Record<string, "circle" | "arrowUp" | "arrowDown" | "square"> = {
  dividend: "circle", split: "square", earnings: "arrowUp", filing: "arrowDown",
};

// PH-VIZ-1: a professional trader chart (TradingView Lightweight Charts, Apache-2.0,
// client-side canvas — no data egress, no paid API). Renders an artifact as real
// candlesticks + a volume pane when it carries OHLCV, else as line series. Crosshair,
// time/price scales, a range selector and log / %-rebase toggles. Descriptive only —
// no forecast/projection lines (PH-VIZ guardrail).

const LINE_COLORS = ["#4f8cff", "#9aa7bd", "#1FA463", "#D9A300"];
const RANGES: [string, number][] = [["1M", 30], ["3M", 90], ["6M", 180], ["1Y", 365], ["5Y", 1825], ["MAX", 0]];

// Normalize a period label to a 'YYYY-MM-DD' the chart accepts; null = unplottable.
function toTime(x: string): string | null {
  if (/^\d{4}-\d{2}-\d{2}$/.test(x)) return x;
  if (/^\d{4}-\d{2}$/.test(x)) return `${x}-01`;
  if (/^\d{4}$/.test(x)) return `${x}-12-31`;
  return null;
}

function daysBefore(last: string, days: number): string {
  const d = new Date(last + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export function TradeChart({ a, onEvidence }: { a: Artifact; onEvidence?: (c: Citation) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const isCandle = (a.candles?.length ?? 0) > 0;
  const lineCount = a.series?.length ?? 0;
  const [range, setRange] = useState("1Y");
  const [logScale, setLogScale] = useState(false);
  const [rebase, setRebase] = useState(false);   // line mode only: index each series to 100

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const chart: IChartApi = createChart(el, {
      width: el.clientWidth,
      height: 260,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#86868C", fontSize: 11 },
      grid: { vertLines: { color: "rgba(150,150,160,0.08)" }, horzLines: { color: "rgba(150,150,160,0.08)" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(150,150,160,0.2)", mode: logScale ? 1 : 0 },
      timeScale: { borderColor: "rgba(150,150,160,0.2)", timeVisible: false },
      handleScale: true,
      handleScroll: true,
    });

    let lastTime: string | null = null;

    if (isCandle) {
      const rows = (a.candles ?? [])
        .map((c) => ({ t: toTime(c.time), c }))
        .filter((r): r is { t: string; c: NonNullable<Artifact["candles"]>[number] } =>
          r.t != null && r.c.open != null && r.c.high != null && r.c.low != null && r.c.close != null);
      const candle = chart.addCandlestickSeries({
        upColor: "#1FA463", downColor: "#D1483A", borderVisible: false,
        wickUpColor: "#1FA463", wickDownColor: "#D1483A",
      });
      candle.setData(rows.map((r) => ({
        time: r.t as Time, open: r.c.open!, high: r.c.high!, low: r.c.low!, close: r.c.close!,
      })));
      const hasVol = rows.some((r) => r.c.volume != null);
      if (hasVol) {
        const vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" });
        vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
        vol.setData(rows.map((r) => ({
          time: r.t as Time, value: r.c.volume ?? 0,
          color: (r.c.close ?? 0) >= (r.c.open ?? 0) ? "rgba(31,164,99,0.4)" : "rgba(209,72,58,0.4)",
        })));
      }
      lastTime = rows.length ? rows[rows.length - 1].t : null;

      // PH-VIZ-2: descriptive price lines + sourced event markers (snapped to the nearest bar);
      // clicking a marker opens its source in the evidence viewer — the chart IS evidence.
      (a.pricelines ?? []).forEach((pl) =>
        candle.createPriceLine({
          price: pl.price, color: pl.color ?? "#86868C", lineStyle: LineStyle.Dashed,
          lineWidth: 1, axisLabelVisible: true, title: pl.label,
        }));
      const times = rows.map((r) => r.t);
      const snap = (d: string): string | null => {
        let r: string | null = null;
        for (const t of times) { if (t <= d) r = t; else break; }
        return r;
      };
      const byTime = new Map<string, ArtifactMarker>();
      const marks: SeriesMarker<Time>[] = [];
      (a.markers ?? []).forEach((m) => {
        const t = snap(m.time);
        if (!t) return;
        byTime.set(t, m);
        marks.push({
          time: t as Time, position: m.position === "aboveBar" ? "aboveBar" : "belowBar",
          color: m.color ?? "#4f8cff", shape: MARKER_SHAPE[m.kind ?? ""] ?? "circle", text: m.label,
        });
      });
      if (marks.length) {
        marks.sort((x, y) => ((x.time as string) < (y.time as string) ? -1 : 1));
        candle.setMarkers(marks);
      }
      if (onEvidence) {
        chart.subscribeClick((param) => {
          const t = param.time as string | undefined;
          const m = t ? byTime.get(t) : undefined;
          if (m) onEvidence({
            tool: "chart", source: m.source ?? undefined, url: m.url ?? undefined,
            snippet: m.snippet ?? m.label, kind: "data", page: m.label, ticker: a.ticker ?? undefined,
          });
        });
      }
    } else {
      a.series.forEach((s, i) => {
        const pts = s.points
          .map((p) => ({ t: toTime(p.x), y: p.y }))
          .filter((p): p is { t: string; y: number } => p.t != null && p.y != null);
        if (!pts.length) return;
        const base = pts[0].y;
        const line = chart.addLineSeries({ color: LINE_COLORS[i % LINE_COLORS.length], lineWidth: 2, title: s.label });
        line.setData(pts.map((p) => ({
          time: p.t as Time,
          value: rebase && base ? ((p.y / base) - 1) * 100 : (s.unit === "ratio" ? p.y * 100 : p.y),
        })));
        const lt = pts[pts.length - 1].t;
        if (!lastTime || lt > lastTime) lastTime = lt;
      });
    }

    // apply the selected range (MAX → fit all)
    const days = RANGES.find(([k]) => k === range)?.[1] ?? 0;
    if (days && lastTime) {
      try {
        chart.timeScale().setVisibleRange({ from: daysBefore(lastTime, days) as Time, to: lastTime as Time });
      } catch { chart.timeScale().fitContent(); }
    } else {
      chart.timeScale().fitContent();
    }

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    return () => { ro.disconnect(); chart.remove(); };
  }, [a, range, logScale, rebase, isCandle]);

  return (
    <div className="tradechart">
      <div className="tc-toolbar">
        <div className="tc-ranges">
          {RANGES.map(([k]) => (
            <button key={k} type="button" className={range === k ? "on" : ""} onClick={() => setRange(k)}>{k}</button>
          ))}
        </div>
        <div className="tc-toggles">
          <button type="button" className={logScale ? "on" : ""} onClick={() => setLogScale((v) => !v)} title="로그 스케일">log</button>
          {!isCandle && lineCount >= 1 && (
            <button type="button" className={rebase ? "on" : ""} onClick={() => setRebase((v) => !v)} title="시작점=100 기준 % 변화">% 기준</button>
          )}
        </div>
      </div>
      <div ref={box} className="tc-canvas" />
    </div>
  );
}
