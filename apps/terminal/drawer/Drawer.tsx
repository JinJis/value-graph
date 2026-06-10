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
import type { GraphCompany, PublishedGraph } from "../canvas/types";
import { CompanyAvatar } from "../components/CompanyAvatar";
import { EdgeInspector } from "../edge/EdgeInspector";
import { ProvenanceCard } from "../provenance/ProvenanceCard";
import type { FigureProvenance } from "../provenance/provenance";
import { buildCompanyView, formatMarketCap, type EdgeLedgers } from "./model";

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

// A relationship figure: label + share + chip, expandable to its provenance card +
// the edge inspector (two ledgers, reconciliation/conflict, supporting claims).
function FigureRow({
  partner,
  share,
  figure,
  ledgers,
}: {
  partner: GraphCompany;
  share: string;
  figure: FigureProvenance;
  ledgers: EdgeLedgers;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li style={{ padding: "4px 0" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          alignItems: "center",
        }}
      >
        <span
          style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}
        >
          <CompanyAvatar company={partner} size={22} />
          <span
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {partner.name}
          </span>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ opacity: 0.85 }}>{share}</span>
          <Chip confidence={figure.confidence} freshness={figure.freshness} />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label="Inspect figure"
            title="Provenance & evidence"
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
      {open && (
        <>
          <ProvenanceCard figure={figure} />
          <EdgeInspector
            detail={ledgers.detail}
            supplierRevShare={ledgers.supplierRevShare}
            customerCostShare={ledgers.customerCostShare}
            sources={figure.sources}
          />
        </>
      )}
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
  const companyByTicker = useMemo(() => {
    const m = new Map<string, GraphCompany>();
    for (const c of graph.companies) m.set(c.ticker, c);
    return m;
  }, [graph]);

  if (!selected || !view) return null;

  const partnerOf = (ticker: string): GraphCompany =>
    companyByTicker.get(ticker) ?? { ticker, name: ticker };
  const self = partnerOf(selected);
  const customerCount = view.products.reduce(
    (n, g) => n + g.customers.length,
    0,
  );
  const supplierCount = view.suppliers.length;

  return (
    <aside
      style={{
        position: "absolute",
        top: 56,
        right: 344, // sits inboard of the 320px Live Context Feed
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
        <div style={{ display: "flex", gap: 10, minWidth: 0 }}>
          <CompanyAvatar company={self} size={40} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{view.name}</div>
            <div style={{ opacity: 0.6 }}>{view.ticker}</div>
            <div style={{ marginTop: 3, fontSize: 11, color: "#7e8ca6" }}>
              Supplies{" "}
              <strong style={{ color: "#9fb4d6" }}>{customerCount}</strong>{" "}
              {customerCount === 1 ? "company" : "companies"} · Bought from{" "}
              <strong style={{ color: "#9fb4d6" }}>{supplierCount}</strong>
            </div>
          </div>
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
            alignSelf: "flex-start",
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
                  partner={partnerOf(c.customer)}
                  share={
                    c.customerCostShare != null
                      ? `${c.customerCostShare.toFixed(1)}% of cost`
                      : "—"
                  }
                  figure={c.provenance}
                  ledgers={c.ledgers}
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
            partner={partnerOf(s.supplier)}
            share={
              s.supplierRevShare != null
                ? `${s.supplierRevShare.toFixed(1)}% of rev`
                : "—"
            }
            figure={s.provenance}
            ledgers={s.ledgers}
          />
        ))}
      </ul>

      <p style={{ marginTop: 14, opacity: 0.45, fontSize: 11 }}>
        Tap ⓘ for a figure&apos;s provenance, both ledgers &amp; supporting
        claims. Not investment advice.
      </p>
    </aside>
  );
}
