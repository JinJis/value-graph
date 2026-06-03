"use client";

// [M6-PROV-02] The per-figure provenance card: value + interval, a confidence chip,
// the freshness line ("as of … · N days old · next: …"), and a link to the actual
// source document. Reserves a disabled "Improve this" hook (Phase 2).

import { confidenceStyle, freshnessColor } from "../canvas/encoding";
import {
  formatFreshnessLine,
  formatInterval,
  formatValue,
  type FigureProvenance,
} from "./provenance";

export function ProvenanceCard({ figure }: { figure: FigureProvenance }) {
  const style = confidenceStyle(figure.confidence);
  return (
    <div
      style={{
        margin: "4px 0 8px",
        padding: "8px 10px",
        background: "#0b111c",
        border: "1px solid #20304a",
        borderRadius: 8,
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>
          {formatValue(figure.value, figure.unit)}
        </span>
        <span style={{ opacity: 0.6 }}>{formatInterval(figure.interval)}</span>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          margin: "4px 0",
        }}
      >
        <span
          title={`freshness: ${figure.freshness}`}
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: freshnessColor(figure.freshness),
          }}
        />
        <span style={{ color: style.colorHex }}>{style.label}</span>
        <span style={{ opacity: 0.5 }}>· {style.style}</span>
      </div>

      <div style={{ opacity: 0.7 }}>
        {formatFreshnessLine(figure.asOf, figure.nextUpdate)}
      </div>

      <div style={{ marginTop: 6 }}>
        <span style={{ opacity: 0.55 }}>Source: </span>
        {figure.sources.length === 0 ? (
          <span style={{ opacity: 0.5 }}>—</span>
        ) : (
          figure.sources.map((s, i) => (
            <span key={s.source_id}>
              {i > 0 && ", "}
              {s.url ? (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "#8fd0ff" }}
                >
                  {s.type ?? "document"}
                </a>
              ) : (
                <span title="no public link" style={{ opacity: 0.7 }}>
                  {s.source_id}
                </span>
              )}
            </span>
          ))
        )}
      </div>

      {/* Phase-2 community contribution hook — disabled in v1. */}
      <button
        type="button"
        disabled
        title="Coming in a later phase"
        style={{
          marginTop: 8,
          background: "transparent",
          color: "#5a6b86",
          border: "1px dashed #2a3a55",
          borderRadius: 6,
          padding: "2px 8px",
          cursor: "not-allowed",
          fontSize: 11,
        }}
      >
        Improve this
      </button>
    </div>
  );
}
