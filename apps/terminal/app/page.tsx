"use client";

// [M5-CANVAS-01] Terminal macro map. Chrome (picker, legend, status) is DOM; the
// supply-chain graph itself is WebGL only (instanced nodes) — never DOM nodes.

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { getPublishedGraph, listThemes } from "../canvas/api";
import { mockMarketFeed } from "../canvas/marketFeed";
import type { PublishedGraph, ThemeSummary } from "../canvas/types";

// R3F renders to <canvas>; it cannot server-render.
const Scene = dynamic(() => import("../canvas/Scene").then((m) => m.Scene), {
  ssr: false,
});

export default function TerminalPage() {
  const [themes, setThemes] = useState<ThemeSummary[]>([]);
  const [themeId, setThemeId] = useState<string>("");
  const [graph, setGraph] = useState<PublishedGraph | null>(null);
  const [status, setStatus] = useState<string>("Loading themes…");

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
        <span style={{ flex: 1 }} />
        <small style={{ opacity: 0.5 }}>Not investment advice.</small>
      </header>

      <div style={{ position: "absolute", inset: 0 }}>
        {graph ? (
          <Scene graph={graph} />
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
