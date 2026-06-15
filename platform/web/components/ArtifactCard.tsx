"use client";

import { useState } from "react";
import { FreshnessDot } from "./SourceCard";

// U3-02: render a connector-backed Artifact as an interactive card — a dependency-free
// SVG line chart (matte palette) with a 차트/표 toggle, source + freshness, drawn gaps.

type ArtifactPoint = { x: string; y: number | null };
type ArtifactSeries = { label: string; unit?: string | null; points: ArtifactPoint[] };
export type Artifact = {
  kind: string;
  title: string;
  series: ArtifactSeries[];
  source?: string | null;
  as_of?: string | null;
  freshness?: string | null;
  ticker?: string | null;
  has_gap?: boolean;
  tool?: string | null;
};

const STROKES = ["#ececee", "#8a8f98", "#3ec46b", "#e0a93b"]; // neutral + sparse accent; distinguishable

function fmt(y: number | null | undefined, unit?: string | null) {
  if (y == null) return "—";
  if (unit === "ratio") return (y * 100).toFixed(1) + "%";
  const abs = Math.abs(y);
  if (abs >= 1e12) return (y / 1e12).toFixed(2) + "T";
  if (abs >= 1e9) return (y / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return (y / 1e6).toFixed(2) + "M";
  return y.toLocaleString();
}

export function ArtifactCard({ a, onPin, onRemove }: { a: Artifact; onPin?: () => void; onRemove?: () => void }) {
  const [table, setTable] = useState(false);
  const [pinned, setPinned] = useState(false);
  const xs = Array.from(new Set(a.series.flatMap((s) => s.points.map((p) => p.x)))).sort();
  const ys = a.series.flatMap((s) => s.points.map((p) => p.y)).filter((v): v is number => v != null);
  const unit = a.series[0]?.unit;
  if (xs.length === 0 || ys.length === 0) return null;
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const W = 520, H = 150, PAD = 10;
  const xPos = (x: string) => (xs.length <= 1 ? W / 2 : PAD + (xs.indexOf(x) / (xs.length - 1)) * (W - 2 * PAD));
  const yPos = (y: number) => (yMax === yMin ? H / 2 : H - PAD - ((y - yMin) / (yMax - yMin)) * (H - 2 * PAD));

  return (
    <div className="artifact">
      <div className="artifact-head">
        <span className="artifact-title">{a.title}</span>
        <FreshnessDot f={a.freshness ?? undefined} />
        <button type="button" className="artifact-toggle" onClick={() => setTable((t) => !t)}>
          {table ? "📈 차트" : "⇄ 표로"}
        </button>
        {onPin && (
          <button type="button" className="artifact-toggle" disabled={pinned}
            onClick={() => { onPin(); setPinned(true); }}>
            {pinned ? "📌 핀됨" : "📌 핀"}
          </button>
        )}
        {onRemove && (
          <button type="button" className="artifact-toggle" onClick={onRemove} title="보드에서 제거">✕</button>
        )}
      </div>

      {table ? (
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
      ) : (
        <svg className="artifact-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={a.title}>
          {a.series.map((s, i) => {
            const pts = s.points.filter((p) => p.y != null);
            const d = pts.map((p, j) => `${j === 0 ? "M" : "L"} ${xPos(p.x).toFixed(1)} ${yPos(p.y as number).toFixed(1)}`).join(" ");
            const stroke = STROKES[i % STROKES.length];
            return (
              <g key={s.label}>
                <path d={d} fill="none" stroke={stroke} strokeWidth={1.6}
                  strokeDasharray={a.has_gap ? "4 3" : undefined} />
                {pts.map((p) => <circle key={p.x} cx={xPos(p.x)} cy={yPos(p.y as number)} r={2.2} fill={stroke} />)}
              </g>
            );
          })}
        </svg>
      )}

      {!table && (
        <div className="artifact-xaxis mono"><span>{xs[0]}</span><span>{xs[xs.length - 1]}</span></div>
      )}
      <div className="artifact-foot">
        <div className="artifact-legend">
          {a.series.map((s, i) => (
            <span key={s.label}><i style={{ background: STROKES[i % STROKES.length] }} /> {s.label}</span>
          ))}
        </div>
        <span className="artifact-src">
          {a.source || "출처"}{a.as_of ? <span className="mono"> · as of {a.as_of}</span> : null}
          {a.has_gap ? <span className="artifact-gap"> · 일부 구간 공백</span> : null}
        </span>
      </div>
    </div>
  );
}
