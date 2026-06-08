"use client";

// [M6-EDGE-03] Edge inspector: the two ledgers (supplier-rev-share <-> customer-cost-
// share — the same trade seen from both sides), the reconciliation summary (point +
// interval + #sources), a CONFLICT banner when flagged, and every SUPPORTS claim with
// its verbatim span + source link.

import { SourceHighlight, type SourceRef as UiSourceRef } from "@valuegraph/ui";
import { useState } from "react";

import type { EdgeDetail, SourceRef } from "../canvas/types";

function sourceLink(sources: SourceRef[], sourceId: string) {
  const ref = sources.find((s) => s.source_id === sourceId);
  if (ref?.url) {
    return (
      <a
        href={ref.url}
        target="_blank"
        rel="noreferrer"
        style={{ color: "#8fd0ff" }}
      >
        {ref.type ?? "document"}
      </a>
    );
  }
  return <span style={{ opacity: 0.6 }}>{sourceId}</span>;
}

function fmt(n: number | null | undefined, suffix = ""): string {
  return n != null ? `${n.toFixed(1)}${suffix}` : "—";
}

export function EdgeInspector({
  detail,
  supplierRevShare,
  customerCostShare,
  sources,
}: {
  detail: EdgeDetail | null;
  supplierRevShare: number | null;
  customerCostShare: number | null;
  sources: SourceRef[];
}) {
  const rec = detail?.reconciliation ?? null;
  const conflict = rec?.status === "conflict";
  const claims = detail?.claims ?? [];
  const [openClaim, setOpenClaim] = useState<number | null>(null);

  const refFor = (sourceId: string): UiSourceRef =>
    sources.find((s) => s.source_id === sourceId) ?? {
      source_id: sourceId,
      has_content: false,
    };

  return (
    <div
      style={{
        margin: "4px 0 8px",
        padding: "8px 10px",
        background: "#0b111c",
        border: `1px solid ${conflict ? "#7a2f2f" : "#20304a"}`,
        borderRadius: 8,
        fontSize: 12,
      }}
    >
      {conflict && (
        <div
          style={{
            background: "#2a1414",
            color: "#f8a5a5",
            border: "1px solid #7a2f2f",
            borderRadius: 6,
            padding: "4px 8px",
            marginBottom: 8,
          }}
        >
          ⚠ Conflict — sources disagree.{" "}
          {rec?.reason && <span style={{ opacity: 0.85 }}>{rec.reason}</span>}
        </div>
      )}

      {/* Both ledgers — one trade, two views. */}
      <div style={{ opacity: 0.55, marginBottom: 2 }}>Two ledgers</div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span>supplier: {fmt(supplierRevShare, "% of rev")}</span>
        <span style={{ opacity: 0.5 }}>↔</span>
        <span>customer: {fmt(customerCostShare, "% of cost")}</span>
      </div>

      {/* Reconciliation summary. */}
      <div style={{ opacity: 0.55, margin: "8px 0 2px" }}>Reconciliation</div>
      {rec ? (
        <div>
          point {fmt(rec.point)}{" "}
          {rec.interval && (
            <span style={{ opacity: 0.7 }}>
              [{rec.interval.low.toFixed(1)} – {rec.interval.high.toFixed(1)}]
            </span>
          )}{" "}
          · {rec.n_sources} source{rec.n_sources === 1 ? "" : "s"} ·{" "}
          <span style={{ color: conflict ? "#f8a5a5" : "#6ee7a8" }}>
            {rec.status}
          </span>
        </div>
      ) : (
        <div style={{ opacity: 0.5 }}>—</div>
      )}

      {/* Supporting (SUPPORTS) claims with verbatim spans. */}
      <div style={{ opacity: 0.55, margin: "8px 0 2px" }}>
        Supporting claims ({claims.length})
      </div>
      {claims.length === 0 ? (
        <div style={{ opacity: 0.5 }}>—</div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {claims.map((c, i) => (
            <li key={`${c.source_id}-${i}`} style={{ marginBottom: 6 }}>
              <div>
                {c.relation}: {fmt(c.value, c.unit ? ` ${c.unit}` : "")}
              </div>
              <div
                style={{
                  opacity: 0.7,
                  fontStyle: "italic",
                  borderLeft: "2px solid #2a3a55",
                  paddingLeft: 6,
                  margin: "2px 0",
                }}
              >
                “{c.text_span}”
              </div>
              <div style={{ opacity: 0.6 }}>
                — {sourceLink(sources, c.source_id)}
                {c.as_of ? ` · ${c.as_of}` : ""}
                {c.text_span && (
                  <>
                    {" · "}
                    <button
                      type="button"
                      onClick={() =>
                        setOpenClaim((cur) => (cur === i ? null : i))
                      }
                      style={{
                        background: "none",
                        border: "none",
                        color: "#8fd0ff",
                        cursor: "pointer",
                        padding: 0,
                        fontSize: 12,
                      }}
                    >
                      {openClaim === i ? "hide source" : "🔍 view in source"}
                    </button>
                  </>
                )}
              </div>
              {openClaim === i && c.text_span && (
                <div
                  style={{
                    marginTop: 6,
                    background: "#fff",
                    color: "#0f172a",
                    borderRadius: 6,
                    padding: 8,
                  }}
                >
                  <SourceHighlight
                    source={refFor(c.source_id)}
                    quote={c.text_span}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
