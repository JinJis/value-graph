"use client";

// [M6-DRAWER-01] Company Drawer: opens on node select. Live price/market cap is shown
// in a distinct REAL-TIME band, separate from the periodic relationship figures
// (which are only as fresh as the last filing). Products (grouped by edge product_ref)
// list who-buys-each with its share; clicking a product highlights those customer
// edges on the canvas. Full provenance cards (M6-PROV-02) + edge inspector (M6-EDGE-03)
// build on this.

import { useMemo, useState } from "react";

import { confidenceStyle, freshnessColor } from "../canvas/encoding";
import { useSelection } from "../canvas/controls";
import { mockMarketFeed } from "../canvas/marketFeed";
import type { PublishedGraph } from "../canvas/types";
import { ProvenanceCard } from "../provenance/ProvenanceCard";
import type { FigureProvenance } from "../provenance/provenance";
import { buildCompanyView, formatMarketCap } from "./model";

function Chip({
  confidence,
  freshness,
}: {
  confidence: string;
  freshness: string;
}) {
  const style = confidenceStyle(confidence);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span
        title={`freshness: ${freshness}`}
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: freshnessColor(freshness),
        }}
      />
      <span style={{ color: style.colorHex, fontSize: 11 }}>{style.label}</span>
    </span>
  );
}

// A relationship figure: label + share + chip, expandable to its provenance card.
function FigureRow({
  label,
  share,
  figure,
}: {
  label: string;
  share: string;
  figure: FigureProvenance;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li style={{ padding: "3px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span>{label}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ opacity: 0.85 }}>{share}</span>
          <Chip confidence={figure.confidence} freshness={figure.freshness} />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label="Provenance"
            title="Show provenance"
            style={{
              background: "transparent",
              color: open ? "#8fd0ff" : "#5a6b86",
              border: "none",
              cursor: "pointer",
              fontSize: 13,
              lineHeight: 1,
            }}
          >
            ⓘ
          </button>
        </span>
      </div>
      {open && <ProvenanceCard figure={figure} />}
    </li>
  );
}

export function Drawer({ graph }: { graph: PublishedGraph }) {
  const selected = useSelection((s) => s.selected);
  const clear = useSelection((s) => s.clear);
  const highlightEdges = useSelection((s) => s.highlightEdges);
  const setHighlightEdges = useSelection((s) => s.setHighlightEdges);

  const view = useMemo(
    () => (selected ? buildCompanyView(graph, selected, mockMarketFeed) : null),
    [graph, selected],
  );

  if (!selected || !view) return null;

  return (
    <aside
      style={{
        position: "absolute",
        top: 56,
        right: 12,
        bottom: 12,
        width: 340,
        zIndex: 20,
        overflowY: "auto",
        background: "#0e1420f2",
        border: "1px solid #1f2a3d",
        borderRadius: 10,
        padding: 16,
        color: "#cdd6e4",
        fontSize: 13,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{view.name}</div>
          <div style={{ opacity: 0.6 }}>{view.ticker}</div>
        </div>
        <button
          type="button"
          onClick={() => clear()}
          aria-label="Close"
          style={{
            background: "transparent",
            color: "#cdd6e4",
            border: "none",
            cursor: "pointer",
            fontSize: 16,
          }}
        >
          ✕
        </button>
      </div>

      {/* REAL-TIME band — visually distinct from the periodic figures below. */}
      <section
        style={{
          marginTop: 12,
          padding: "8px 10px",
          borderRadius: 8,
          background: "#0c1a12",
          border: "1px solid #1c5236",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            opacity: 0.8,
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "#36d399",
            }}
          />
          <small>
            {view.market.live ? "LIVE" : "DELAYED / MOCK"} · real-time
          </small>
        </div>
        <div style={{ fontSize: 18, marginTop: 2 }}>
          {formatMarketCap(view.market.marketCap)}{" "}
          <span style={{ fontSize: 12, opacity: 0.6 }}>market cap</span>
        </div>
      </section>

      {/* PERIODIC figures — only as fresh as the last filing. */}
      <div style={{ marginTop: 14, opacity: 0.55, fontSize: 11 }}>
        RELATIONSHIPS · periodic (as of last filing)
      </div>

      <h3 style={{ margin: "8px 0 4px", fontSize: 13 }}>
        Supplies to {view.products.length === 0 && <small>— none</small>}
      </h3>
      {view.products.map((group) => {
        const active =
          highlightEdges != null &&
          group.edgeKeys.every((k) => highlightEdges.includes(k)) &&
          highlightEdges.length === group.edgeKeys.length;
        return (
          <div key={group.product} style={{ marginBottom: 8 }}>
            <button
              type="button"
              onClick={() => setHighlightEdges(active ? null : group.edgeKeys)}
              title="Highlight these customer edges on the map"
              style={{
                width: "100%",
                textAlign: "left",
                background: active ? "#1b2840" : "transparent",
                color: "#cdd6e4",
                border: "1px solid #243149",
                borderRadius: 6,
                padding: "4px 8px",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              {group.product} <span style={{ opacity: 0.5 }}>›</span>
            </button>
            <ul
              style={{ listStyle: "none", margin: "4px 0 0", padding: "0 4px" }}
            >
              {group.customers.map((c) => (
                <FigureRow
                  key={c.key}
                  label={c.customer}
                  share={
                    c.customerCostShare != null
                      ? `${c.customerCostShare.toFixed(1)}% of cost`
                      : "—"
                  }
                  figure={c.provenance}
                />
              ))}
            </ul>
          </div>
        );
      })}

      <h3 style={{ margin: "12px 0 4px", fontSize: 13 }}>
        Supplied by {view.suppliers.length === 0 && <small>— none</small>}
      </h3>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {view.suppliers.map((s) => (
          <FigureRow
            key={s.key}
            label={s.supplier}
            share={
              s.supplierRevShare != null
                ? `${s.supplierRevShare.toFixed(1)}% of rev`
                : "—"
            }
            figure={s.provenance}
          />
        ))}
      </ul>

      <p style={{ marginTop: 14, opacity: 0.45, fontSize: 11 }}>
        Tap ⓘ for a figure&apos;s source &amp; freshness. Edge inspector arrives
        next. Not investment advice.
      </p>
    </aside>
  );
}
