"use client";

import { SourceHighlight, type SourceRef } from "@valuegraph/ui";
import { useCallback, useEffect, useState } from "react";

import {
  getStagingGraph,
  type EdgeClaimDetail,
  type EdgeSourceRef,
  type StagingGraph,
} from "../lib/api";

// Lists the latest build's trade edges and, per supporting claim, shows the verbatim quote
// + a "View in source" action that opens the shared SourceHighlight viewer (highlights the
// exact span in the source document, or deep-links the original). Refresh via `refreshKey`.

const edgeKey = (supplier: string, customer: string) =>
  `${supplier}->${customer}`;

function refFor(
  refs: EdgeSourceRef[] | undefined,
  sourceId: string,
): SourceRef {
  const found = refs?.find((r) => r.source_id === sourceId);
  return found ?? { source_id: sourceId, has_content: false };
}

function Modal({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 10,
          padding: 16,
          width: "min(820px, 100%)",
          maxHeight: "85vh",
          overflow: "auto",
        }}
      >
        <div style={{ textAlign: "right" }}>
          <button type="button" onClick={onClose} style={{ fontSize: 13 }}>
            ✕ Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

interface Viewing {
  source: SourceRef;
  quote: string;
  label: string;
}

function ClaimRow({
  claim,
  refs,
  onView,
}: {
  claim: EdgeClaimDetail;
  refs: EdgeSourceRef[] | undefined;
  onView: (v: Viewing) => void;
}) {
  const ref = refFor(refs, claim.source_id);
  const value = claim.value == null ? "—" : `${claim.value}${claim.unit ?? ""}`;
  return (
    <li style={{ margin: "6px 0", fontSize: 13 }}>
      <span style={{ fontFamily: "ui-monospace, monospace", color: "#475569" }}>
        {claim.relation}
      </span>{" "}
      <strong>{value}</strong>
      {claim.text_span && (
        <div
          style={{
            borderLeft: "2px solid #cbd5e1",
            paddingLeft: 8,
            margin: "2px 0",
            color: "#475569",
            fontStyle: "italic",
          }}
        >
          “{claim.text_span}”
        </div>
      )}
      <button
        type="button"
        onClick={() =>
          onView({
            source: ref,
            quote: claim.text_span,
            label: `${claim.relation} · ${ref.has_content ? (ref.content_type ?? "document") : "external source"}`,
          })
        }
        disabled={!claim.text_span}
        style={{ fontSize: 12 }}
      >
        🔍 View in source
      </button>
    </li>
  );
}

export function EdgeSourcePanel({
  themeId,
  refreshKey = 0,
}: {
  themeId: string;
  refreshKey?: number;
}) {
  const [graph, setGraph] = useState<StagingGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [viewing, setViewing] = useState<Viewing | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setGraph(await getStagingGraph(themeId));
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [themeId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const edges = graph?.edges ?? [];

  return (
    <section
      style={{
        border: "1px solid #cbd5e1",
        borderRadius: 8,
        padding: "12px 16px",
        margin: "1rem 0",
        background: "#f8fafc",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <strong style={{ fontSize: 14 }}>Trade edges &amp; sources</strong>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          style={{ fontSize: 12 }}
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
        <small style={{ color: "#64748b" }}>
          every edge traces to the exact span in its source
        </small>
      </div>

      {error && (
        <p style={{ color: "#b91c1c", fontSize: 13 }}>Couldn’t load: {error}</p>
      )}
      {!graph ? (
        !error && (
          <p style={{ fontSize: 13, color: "#64748b" }}>
            {loading ? "Loading…" : "No build yet — run the build first."}
          </p>
        )
      ) : edges.length === 0 ? (
        <p style={{ fontSize: 13, color: "#64748b" }}>
          Build v{graph.snapshot_version} has no publishable trade edges yet.
        </p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: "8px 0" }}>
          {edges.map((e, i) => {
            const supplier = String(e.supplier ?? "");
            const customer = String(e.customer ?? "");
            const key = edgeKey(supplier, customer);
            const detail = graph.edge_details[key];
            const refs = graph.edge_sources[key];
            const isOpen = open[key];
            return (
              <li
                key={`${key}-${i}`}
                style={{ borderTop: "1px solid #e2e8f0", padding: "6px 0" }}
              >
                <button
                  type="button"
                  onClick={() => setOpen((o) => ({ ...o, [key]: !o[key] }))}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontSize: 14,
                    padding: 0,
                  }}
                >
                  {isOpen ? "▾" : "▸"} <strong>{supplier}</strong> →{" "}
                  <strong>{customer}</strong>{" "}
                  <span style={{ color: "#64748b", fontSize: 12 }}>
                    {String(e.confidence ?? "")} · {String(e.freshness ?? "")} ·{" "}
                    {refs?.length ?? 0} source(s)
                  </span>
                </button>
                {isOpen && (
                  <ul
                    style={{
                      listStyle: "none",
                      padding: "4px 0 0 18px",
                      margin: 0,
                    }}
                  >
                    {(detail?.claims ?? []).length === 0 ? (
                      <li style={{ fontSize: 12, color: "#64748b" }}>
                        No supporting claims recorded.
                      </li>
                    ) : (
                      detail.claims.map((c, j) => (
                        <ClaimRow
                          key={j}
                          claim={c}
                          refs={refs}
                          onView={setViewing}
                        />
                      ))
                    )}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {viewing && (
        <Modal onClose={() => setViewing(null)}>
          <h3 style={{ marginTop: 0, fontSize: 15 }}>
            Source · {viewing.label}
          </h3>
          <SourceHighlight source={viewing.source} quote={viewing.quote} />
        </Modal>
      )}
    </section>
  );
}
