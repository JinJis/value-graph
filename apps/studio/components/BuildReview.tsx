"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";

import {
  getThemeReview,
  type ReviewCompany,
  type ReviewRelationship,
  type ThemeReview,
} from "../lib/api";

// One read-only map of EVERYTHING a theme has, for the pre-publish review: the data
// pipeline as boxes (where it's full / empty), a per-company coverage matrix, and the
// supplier→customer relationships the build produced — so "why are trade edges 0?" is
// answerable at a glance.

type Tone = "ok" | "warn" | "bad" | "idle";

const TONE: Record<Tone, { border: string; bg: string; fg: string }> = {
  ok: { border: "#16a34a", bg: "#f0fdf4", fg: "#15803d" },
  warn: { border: "#d97706", bg: "#fffbeb", fg: "#b45309" },
  bad: { border: "#dc2626", bg: "#fef2f2", fg: "#b91c1c" },
  idle: { border: "#cbd5e1", bg: "#f8fafc", fg: "#64748b" },
};

const TH: CSSProperties = {
  textAlign: "left",
  borderBottom: "1px solid #e2e8f0",
  padding: "6px 8px",
  fontWeight: 600,
  color: "#475569",
};
const TD: CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid #f1f5f9",
};

function StatBox({
  title,
  value,
  sub,
  tone,
}: {
  title: string;
  value: string;
  sub?: string;
  tone: Tone;
}) {
  const t = TONE[tone];
  return (
    <div
      style={{
        border: `1px solid ${t.border}`,
        background: t.bg,
        borderRadius: 8,
        padding: "8px 10px",
        minWidth: 116,
      }}
    >
      <div style={{ fontSize: 11, color: "#64748b" }}>{title}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: t.fg }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#64748b" }}>{sub}</div>}
    </div>
  );
}

function Arrow({ down = false }: { down?: boolean }) {
  return (
    <div
      style={{
        color: "#94a3b8",
        fontSize: 18,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: down ? "2px 0" : "0 4px",
      }}
    >
      {down ? "↓" : "→"}
    </div>
  );
}

// Inputs → Claims → Edges → Publish, each colored by how full it is. The first red box in
// the Claims→Edges→Publish chain is where the build breaks.
function PipelineMap({ r }: { r: ThemeReview }) {
  const c = r.counts;
  const finTone: Tone = !c.companies
    ? "idle"
    : c.financials_covered === 0
      ? "bad"
      : c.financials_covered < c.companies
        ? "warn"
        : "ok";
  const calTone: Tone = !c.companies
    ? "idle"
    : c.calendar_covered === 0
      ? "bad"
      : c.calendar_covered < c.companies
        ? "warn"
        : "ok";
  const srcTone: Tone = c.source_documents
    ? "ok"
    : c.source_citations
      ? "warn"
      : "bad";
  const claimTone: Tone = c.claims > 0 ? "ok" : "bad";
  const edgeTone: Tone =
    c.publishable_edges > 0 ? "ok" : c.gap_edges > 0 ? "warn" : "bad";
  const pubTone: Tone = c.publishable_edges > 0 ? "ok" : "bad";

  return (
    <div
      style={{
        display: "flex",
        gap: 6,
        alignItems: "stretch",
        flexWrap: "wrap",
        margin: "8px 0 4px",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <StatBox
          title="Blueprint"
          value={`${c.companies}`}
          sub="companies"
          tone={c.companies ? "ok" : "bad"}
        />
        <StatBox
          title="Financials"
          value={`${c.financials_covered}/${c.companies}`}
          sub="revenue on file"
          tone={finTone}
        />
        <StatBox
          title="Calendar"
          value={`${c.calendar_covered}/${c.companies}`}
          sub="next filing"
          tone={calTone}
        />
        <StatBox
          title="Sources"
          value={`${c.source_documents}`}
          sub={`${c.source_documents} doc · ${c.source_citations} cite`}
          tone={srcTone}
        />
      </div>
      <Arrow />
      <div style={{ display: "flex", alignItems: "center" }}>
        <StatBox
          title="Claims (S1)"
          value={`${c.claims}`}
          sub="extracted trades"
          tone={claimTone}
        />
      </div>
      <Arrow />
      <div style={{ display: "flex", alignItems: "center" }}>
        <StatBox
          title="Edges"
          value={`${c.publishable_edges} / ${c.gap_edges}`}
          sub={`publishable / gap${c.estimated_edges ? ` · ${c.estimated_edges} est` : ""}`}
          tone={edgeTone}
        />
      </div>
      <Arrow />
      <div style={{ display: "flex", alignItems: "center" }}>
        <StatBox
          title="Publish"
          value={c.publishable_edges > 0 ? "ready" : "blocked"}
          sub={`${Math.round(r.completeness * 100)}% complete`}
          tone={pubTone}
        />
      </div>
    </div>
  );
}

// A plain-language pointer to where the pipeline breaks, tied to the actual counts.
function BreakNote({ r }: { r: ThemeReview }) {
  const c = r.counts;
  let msg: string | null = null;
  if (!c.companies)
    msg =
      "No blueprint companies — generate a blueprint first; everything downstream depends on it.";
  else if (c.claims === 0)
    msg =
      "The chain breaks at Claims: 0 trades were extracted. Financials, Calendar and citations don't create trades — only Deep Research (Research & build) or an uploaded filing that discloses a supplier→customer trade does. Run 'Research & build' on the Build step (with a valid API key), or upload a filing with trade disclosures.";
  else if (c.publishable_edges === 0 && c.gap_edges > 0)
    msg = `${c.gap_edges} relationship(s) were found but none are publishable yet — they're drawn as gaps (ghosts). Usually a missing next_expected_update (fill the Disclosure Calendar) or an estimate with no dated source. You can still publish best-effort.`;
  else if (c.publishable_edges === 0)
    msg = "No relationships were produced — see the per-company claims below.";
  if (!msg) return null;
  return (
    <div
      style={{
        border: "1px solid #fca5a5",
        background: "#fef2f2",
        color: "#7f1d1d",
        borderRadius: 8,
        padding: "8px 12px",
        margin: "8px 0",
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      ⛔ {msg}
    </div>
  );
}

function chip(ok: boolean, label: string) {
  return (
    <span
      style={{
        fontSize: 11,
        padding: "1px 6px",
        borderRadius: 999,
        background: ok ? "#dcfce7" : "#fee2e2",
        color: ok ? "#15803d" : "#b91c1c",
      }}
    >
      {label}
    </span>
  );
}

function num(n: number) {
  return <span style={{ color: n === 0 ? "#cbd5e1" : "#0f172a" }}>{n}</span>;
}

function CompanyTable({ companies }: { companies: ReviewCompany[] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}
      >
        <thead>
          <tr>
            <th style={TH}>Company</th>
            <th style={TH}>Financials</th>
            <th style={TH}>Calendar</th>
            <th style={TH} title="claims mentioning this company">
              Claims
            </th>
            <th style={TH} title="publishable edges where it is the supplier">
              ▲ supplies
            </th>
            <th style={TH} title="publishable edges where it is the customer">
              ▼ buys
            </th>
            <th style={TH} title="gap (ghost) edges it appears in">
              Gaps
            </th>
            <th style={TH} title="OPEN tickets targeting it">
              Tickets
            </th>
          </tr>
        </thead>
        <tbody>
          {companies.map((c) => (
            <tr key={c.ticker}>
              <td style={TD}>
                <strong>{c.ticker}</strong>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  {c.name}
                  {c.role ? ` · ${c.role}` : ""}
                </div>
              </td>
              <td style={TD}>
                {c.has_financials
                  ? chip(true, c.financials_buckets.join(", ") || "ok")
                  : chip(false, "no revenue")}
              </td>
              <td style={TD}>
                {c.has_calendar
                  ? chip(true, c.next_update ?? "set")
                  : chip(false, "no date")}
              </td>
              <td style={TD}>{num(c.claims)}</td>
              <td style={TD}>{num(c.out_edges)}</td>
              <td style={TD}>{num(c.in_edges)}</td>
              <td style={TD}>{num(c.gap_edges)}</td>
              <td style={TD}>{num(c.open_tickets)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const STATE_TONE: Record<ReviewRelationship["state"], Tone> = {
  publishable: "ok",
  estimated: "warn",
  conflict: "bad",
  gap: "idle",
};

function RelationshipList({ rels }: { rels: ReviewRelationship[] }) {
  if (rels.length === 0)
    return (
      <p style={{ color: "#64748b", fontSize: 13 }}>
        No supplier→customer relationships yet. Edges are built from extracted
        claims — see the break note above and the per-company “Claims” column.
      </p>
    );
  // Publishable first, then estimated/conflict, then gaps.
  const order = { publishable: 0, estimated: 1, conflict: 2, gap: 3 };
  const sorted = [...rels].sort((a, b) => order[a.state] - order[b.state]);
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}
      >
        <thead>
          <tr>
            <th style={TH}>Relationship</th>
            <th style={TH}>State</th>
            <th style={TH}>Cost share</th>
            <th style={TH}>Confidence · freshness</th>
            <th style={TH} title="independent sources behind the figure">
              Src
            </th>
            <th style={TH}>Note</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((e) => {
            const t = TONE[STATE_TONE[e.state]];
            const share =
              e.customer_cost_share != null
                ? `${e.customer_cost_share.toFixed(1)}%` +
                  (e.interval_low != null && e.interval_high != null
                    ? ` [${e.interval_low.toFixed(1)}–${e.interval_high.toFixed(1)}]`
                    : "")
                : "—";
            return (
              <tr key={`${e.supplier}->${e.customer}`}>
                <td style={TD}>
                  <strong>{e.supplier}</strong> → {e.customer}
                </td>
                <td style={TD}>
                  <span
                    style={{
                      fontSize: 11,
                      padding: "1px 8px",
                      borderRadius: 999,
                      border: `1px solid ${t.border}`,
                      background: t.bg,
                      color: t.fg,
                    }}
                  >
                    {e.state}
                  </span>
                </td>
                <td style={TD}>{share}</td>
                <td style={TD}>
                  {e.confidence ?? "—"}
                  {e.freshness ? ` · ${e.freshness}` : ""}
                </td>
                <td style={TD}>{num(e.n_sources)}</td>
                <td style={{ ...TD, color: "#64748b", maxWidth: 320 }}>
                  {e.reason ?? (e.as_of ? `as of ${e.as_of}` : "")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function BuildReview({
  themeId,
  refreshKey = 0,
}: {
  themeId: string;
  refreshKey?: number;
}) {
  const [review, setReview] = useState<ThemeReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReview(await getThemeReview(themeId));
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

  if (error)
    return (
      <p style={{ color: "crimson" }}>
        Couldn’t load the review: {error}{" "}
        <button type="button" onClick={() => void load()}>
          retry
        </button>
      </p>
    );
  if (!review)
    return (
      <p style={{ color: "#64748b" }}>{loading ? "Loading review…" : ""}</p>
    );

  const r = review;
  const section: CSSProperties = { margin: "18px 0 4px" };
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <h3 style={{ margin: 0 }}>
          Data map{" "}
          <small style={{ color: "#64748b", fontWeight: 400 }}>
            {r.has_build
              ? `build v${r.build_version} · ${Math.round(r.completeness * 100)}% publishable`
              : "no build yet"}
          </small>
        </h3>
        <button type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <PipelineMap r={r} />
      <BreakNote r={r} />

      <h4 style={section}>Per-company coverage ({r.companies.length})</h4>
      {r.companies.length === 0 ? (
        <p style={{ color: "#64748b", fontSize: 13 }}>
          No blueprint companies.
        </p>
      ) : (
        <CompanyTable companies={r.companies} />
      )}

      <h4 style={section}>
        Relationships ({r.counts.publishable_edges} publishable ·{" "}
        {r.counts.gap_edges} gap)
      </h4>
      <RelationshipList rels={r.relationships} />
    </div>
  );
}
