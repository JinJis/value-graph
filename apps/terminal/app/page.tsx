"use client";

// [M5-CANVAS-01] Terminal macro map. Chrome (picker, legend, status) is DOM; the
// supply-chain graph itself is WebGL only (instanced nodes) — never DOM nodes.

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { getPublishedGraph, listThemes } from "../canvas/api";
import { useSelection } from "../canvas/controls";
import { computeDepths } from "../canvas/depth";
import {
  CONFIDENCE_LEGEND,
  FRESHNESS_LEGEND,
  type LegendEntry,
} from "../canvas/encoding";
import { mockMarketFeed } from "../canvas/marketFeed";
import type { PublishedGraph, ThemeSummary } from "../canvas/types";
import { Drawer } from "../drawer/Drawer";
import { FeedPanel } from "../feed/FeedPanel";
import { TimelinePanel } from "../timeline/TimelinePanel";
import { buildTimeline } from "../timeline/timeline";

// R3F renders to <canvas>; it cannot server-render.
const Scene = dynamic(() => import("../canvas/Scene").then((m) => m.Scene), {
  ssr: false,
});

function LegendRow({ entry, dot }: { entry: LegendEntry; dot: boolean }) {
  return (
    <li style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span
        style={{
          width: dot ? 9 : 16,
          height: dot ? 9 : 3,
          borderRadius: dot ? "50%" : 1,
          background: entry.colorHex,
          flex: "0 0 auto",
        }}
      />
      <span>
        {entry.label} <span style={{ opacity: 0.55 }}>· {entry.hint}</span>
      </span>
    </li>
  );
}

// Legend (DOM chrome) — explains the visual data-quality encoding.
function Legend() {
  return (
    <aside
      style={{
        position: "absolute",
        left: 16,
        bottom: 16,
        zIndex: 10,
        background: "#0e1420dd",
        border: "1px solid #1f2a3d",
        borderRadius: 8,
        padding: "10px 12px",
        fontSize: 12,
        color: "#cdd6e4",
        lineHeight: 1.6,
        maxWidth: 240,
      }}
    >
      <div style={{ opacity: 0.7, marginBottom: 4 }}>Confidence (edge)</div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {CONFIDENCE_LEGEND.map((e) => (
          <LegendRow key={e.label} entry={e} dot={false} />
        ))}
      </ul>
      <div style={{ opacity: 0.7, margin: "8px 0 4px" }}>Freshness (dot)</div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {FRESHNESS_LEGEND.map((e) => (
          <LegendRow key={e.label} entry={e} dot />
        ))}
      </ul>
    </aside>
  );
}

export default function TerminalPage() {
  const [themes, setThemes] = useState<ThemeSummary[]>([]);
  const [themeId, setThemeId] = useState<string>("");
  const [graph, setGraph] = useState<PublishedGraph | null>(null);
  const [status, setStatus] = useState<string>("Loading themes…");
  const [depthLimit, setDepthLimit] = useState<number>(99);
  const [showTimeline, setShowTimeline] = useState(false);
  const selected = useSelection((s) => s.selected);
  const clearSelection = useSelection((s) => s.clear);

  const timeline = useMemo(
    () => (graph ? buildTimeline(graph) : null),
    [graph],
  );

  const { depth, maxDepth } = useMemo(
    () =>
      graph
        ? computeDepths(graph.companies, graph.edges)
        : { depth: new Map<string, number>(), maxDepth: 1 },
    [graph],
  );

  useEffect(() => {
    listThemes()
      .then((t) => {
        setThemes(t);
        if (t.length === 0) setStatus("No themes yet.");
        else setThemeId((id) => id || t[0].id);
      })
      .catch((e) => setStatus(`Could not reach the engine: ${String(e)}`));
  }, []);

  useEffect(() => {
    if (!themeId) return;
    setGraph(null);
    setStatus("Loading published graph…");
    getPublishedGraph(themeId)
      .then((g) => {
        if (!g) {
          setStatus("This theme has no published graph yet.");
          return;
        }
        setGraph(g);
        setStatus("");
      })
      .catch((e) => setStatus(`Could not load graph: ${String(e)}`));
  }, [themeId]);

  // Default to showing every tier when a new graph loads.
  useEffect(() => {
    setDepthLimit(maxDepth);
  }, [maxDepth]);

  return (
    <main
      style={{
        position: "fixed",
        inset: 0,
        background: "#0a0e16",
        color: "#cdd6e4",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <header
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          zIndex: 10,
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 16px",
          background: "linear-gradient(#0a0e16ee, #0a0e1600)",
        }}
      >
        <strong style={{ letterSpacing: 0.3 }}>ValueGraph</strong>
        <select
          value={themeId}
          onChange={(e) => setThemeId(e.target.value)}
          style={{
            background: "#141b28",
            color: "#cdd6e4",
            border: "1px solid #263247",
            borderRadius: 6,
            padding: "4px 8px",
          }}
        >
          {themes.length === 0 && <option value="">—</option>}
          {themes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        {graph && (
          <small style={{ opacity: 0.7 }}>
            {graph.companies.length} nodes · published v{graph.snapshot_version}{" "}
            · {Math.round(graph.completeness * 100)}% complete ·{" "}
            {mockMarketFeed.live ? "live" : "delayed/mock"} market caps
          </small>
        )}
        {selected && (
          <button
            type="button"
            onClick={() => clearSelection()}
            title="Clear selection"
            style={{
              background: "#1b2840",
              color: "#cdd6e4",
              border: "1px solid #2f4a73",
              borderRadius: 999,
              padding: "2px 10px",
              cursor: "pointer",
            }}
          >
            {selected} ✕
          </button>
        )}
        <span style={{ flex: 1 }} />
        {graph && maxDepth > 1 && (
          <label
            style={{ display: "flex", alignItems: "center", gap: 6 }}
            title="Reveal deeper supply tiers"
          >
            <small style={{ opacity: 0.7 }}>Depth</small>
            <input
              type="range"
              min={1}
              max={maxDepth}
              step={1}
              value={Math.min(depthLimit, maxDepth)}
              onChange={(e) => setDepthLimit(Number(e.target.value))}
            />
            <small style={{ width: 36, opacity: 0.7 }}>
              {Math.min(depthLimit, maxDepth)}/{maxDepth}
            </small>
          </label>
        )}
        {graph && timeline && timeline.entries.length > 0 && (
          <button
            type="button"
            onClick={() => setShowTimeline((v) => !v)}
            title="Upcoming data updates"
            style={{
              background: showTimeline ? "#1b2840" : "transparent",
              color: "#cdd6e4",
              border: "1px solid #2f4a73",
              borderRadius: 999,
              padding: "2px 10px",
              cursor: "pointer",
            }}
          >
            ⏱ Updates
            {timeline.overdue > 0 && (
              <span style={{ color: "#f87272" }}>
                {" "}
                · {timeline.overdue} overdue
              </span>
            )}
          </button>
        )}
        <small style={{ opacity: 0.5 }}>Not investment advice.</small>
      </header>

      {graph && !showTimeline && <Legend />}
      {graph && <Drawer graph={graph} />}
      {graph && <FeedPanel themeId={themeId} />}
      {graph && timeline && showTimeline && (
        <TimelinePanel
          timeline={timeline}
          onClose={() => setShowTimeline(false)}
        />
      )}

      <div style={{ position: "absolute", inset: 0 }}>
        {graph ? (
          <Scene graph={graph} depth={depth} depthLimit={depthLimit} />
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              opacity: 0.7,
            }}
          >
            {status}
          </div>
        )}
      </div>
    </main>
  );
}
