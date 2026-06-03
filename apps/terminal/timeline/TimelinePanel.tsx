"use client";

// [M7-NEXT-02] Theme upcoming-update timeline. Lists every edge's next expected refresh
// soonest-first; overdue (stale) items are flagged red at the top so gaps in freshness
// are obvious. Selecting an edge's row highlights it on the canvas.

import { useSelection } from "../canvas/controls";
import { type Timeline, untilLabel } from "./timeline";

export function TimelinePanel({
  timeline,
  onClose,
}: {
  timeline: Timeline;
  onClose: () => void;
}) {
  const setHighlightEdges = useSelection((s) => s.setHighlightEdges);
  const { entries, overdue } = timeline;

  return (
    <aside
      style={{
        position: "absolute",
        top: 56,
        left: 12,
        bottom: 12,
        width: 300,
        zIndex: 18,
        overflowY: "auto",
        background: "#0e1420f2",
        border: "1px solid #1f2a3d",
        borderRadius: 10,
        padding: 14,
        color: "#cdd6e4",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <strong style={{ fontSize: 13 }}>Upcoming updates</strong>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          style={{
            background: "transparent",
            color: "#cdd6e4",
            border: "none",
            cursor: "pointer",
            fontSize: 14,
          }}
        >
          ✕
        </button>
      </div>
      <div style={{ opacity: 0.7, marginTop: 2 }}>
        {entries.length} tracked ·{" "}
        <span style={{ color: overdue > 0 ? "#f87272" : "#36d399" }}>
          {overdue} overdue
        </span>
      </div>

      {entries.length === 0 && (
        <p style={{ opacity: 0.6, marginTop: 12 }}>
          No scheduled updates yet (publish a theme with a disclosure calendar).
        </p>
      )}

      <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0 }}>
        {entries.map((e) => (
          <li
            key={e.key}
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 8,
              padding: "6px 0",
              borderTop: "1px solid #1a2336",
              cursor: "pointer",
            }}
            title="Highlight on map"
            onClick={() => setHighlightEdges([e.key])}
          >
            <span>
              {e.stale && <span style={{ color: "#f87272" }}>● </span>}
              {e.label}
            </span>
            <span
              style={{
                whiteSpace: "nowrap",
                color: e.stale ? "#f87272" : "#9fb0c8",
              }}
            >
              {e.nextUpdate} · {untilLabel(e.daysUntil)}
            </span>
          </li>
        ))}
      </ul>
    </aside>
  );
}
