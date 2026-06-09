"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getBuildDiagnostics,
  type BuildDiagnostics as Diag,
  type DiagFinding,
  type DiagRunInfo,
  type DiagStageCounts,
} from "../lib/api";

// A read-only "why is the graph empty / what's missing" panel. Aggregates every build
// signal (blueprint, source documents, financials, last-run per-stage counts, the assembled
// build) and a plain-language diagnosis. Refresh it after a run via the `refreshKey` prop.

const LEVEL: Record<DiagFinding["level"], { color: string; icon: string }> = {
  error: { color: "#b91c1c", icon: "✗" },
  warn: { color: "#b45309", icon: "⚠" },
  ok: { color: "#15803d", icon: "✓" },
};

// The pipeline stages, in order, so the admin can see exactly where counts drop to zero.
const STAGES: { key: keyof DiagStageCounts; label: string }[] = [
  { key: "documents", label: "docs" },
  { key: "claims", label: "claims" },
  { key: "edges", label: "edges" },
  { key: "reconciled", label: "reconciled" },
  { key: "estimated", label: "estimated" },
  { key: "scored", label: "scored" },
  { key: "gap_results", label: "gaps" },
];

function StagePipeline({ stages }: { stages: DiagStageCounts }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 6,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      {STAGES.map((s, i) => {
        const n = stages[s.key];
        return (
          <span
            key={s.key}
            style={{ display: "flex", alignItems: "center", gap: 6 }}
          >
            <span
              style={{
                fontSize: 12,
                padding: "2px 8px",
                borderRadius: 6,
                background: n > 0 ? "#0f172a" : "#fee2e2",
                color: n > 0 ? "#e2e8f0" : "#b91c1c",
                fontFamily: "ui-monospace, monospace",
              }}
              title={`${s.label}: ${n}`}
            >
              {s.label} {n}
            </span>
            {i < STAGES.length - 1 && (
              <span style={{ color: "#94a3b8" }}>→</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div
      style={{
        border: "1px solid #e2e8f0",
        borderRadius: 8,
        padding: "8px 12px",
        minWidth: 120,
      }}
    >
      <div style={{ fontSize: 12, color: "#64748b" }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: tone ?? "#0f172a" }}>
        {value}
      </div>
    </div>
  );
}

function runLabel(r: DiagRunInfo): string {
  const when = new Date(r.created_at).toLocaleString();
  const counts = r.stages
    ? ` · ${r.stages.claims} claims · ${r.stages.edges} edges`
    : "";
  return `${r.trigger} · ${r.status}${counts} — ${when}`;
}

export function BuildDiagnostics({
  themeId,
  refreshKey = 0,
}: {
  themeId: string;
  refreshKey?: number;
}) {
  const [diag, setDiag] = useState<Diag | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDiag(await getBuildDiagnostics(themeId));
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

  const fin = diag?.financials;
  const missingFin = fin?.missing ?? [];

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
        <strong style={{ fontSize: 14 }}>Build diagnostics</strong>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          style={{ fontSize: 12 }}
        >
          {loading ? "Checking…" : "Refresh"}
        </button>
        <small style={{ color: "#64748b" }}>
          what data exists, what the last run produced, and what’s missing
        </small>
      </div>

      {error && (
        <p style={{ color: "#b91c1c", fontSize: 13 }}>Couldn’t load: {error}</p>
      )}
      {!diag ? (
        !error && <p style={{ fontSize: 13, color: "#64748b" }}>Loading…</p>
      ) : (
        <>
          {/* Plain-language diagnosis — the headline. */}
          <ul style={{ listStyle: "none", padding: 0, margin: "10px 0" }}>
            {diag.findings.map((f, i) => (
              <li
                key={i}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "baseline",
                  margin: "4px 0",
                }}
              >
                <span style={{ color: LEVEL[f.level].color, fontWeight: 700 }}>
                  {LEVEL[f.level].icon}
                </span>
                <span style={{ fontSize: 13 }}>
                  {f.message}
                  {f.action && (
                    <span style={{ color: "#2563eb" }}> → {f.action}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>

          {/* Inputs at a glance. */}
          <div
            style={{
              display: "flex",
              gap: 10,
              flexWrap: "wrap",
              margin: "8px 0",
            }}
          >
            <Stat
              label="Blueprint companies"
              value={String(diag.blueprint_companies)}
              tone={diag.blueprint_companies >= 2 ? undefined : "#b45309"}
            />
            <Stat
              label="Source documents"
              value={`${diag.sources.documents}`}
              tone={diag.sources.documents > 0 ? undefined : "#b45309"}
            />
            <Stat
              label="URL citations"
              value={String(diag.sources.citations)}
            />
            <Stat
              label={`Financials (${fin?.required.join("/") ?? ""})`}
              value={`${fin?.covered ?? 0}/${fin?.total ?? 0}`}
              tone={missingFin.length === 0 ? "#15803d" : "#b45309"}
            />
            <Stat
              label="Disclosure Calendar"
              value={`${diag.calendar_covered}/${diag.blueprint_companies}`}
              tone={
                diag.calendar_covered > 0 || diag.blueprint_companies === 0
                  ? undefined
                  : "#b45309"
              }
            />
            <Stat
              label="Publishable / total"
              value={`${diag.build.publishable_edges}/${diag.build.total_edges}`}
              tone={diag.build.total_edges > 0 ? undefined : "#b91c1c"}
            />
          </div>

          {/* Where the last run dropped to zero. */}
          {diag.last_run?.stages && (
            <div style={{ margin: "10px 0" }}>
              <div style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>
                Last run pipeline (S1→S7) — {diag.last_run.trigger} ·{" "}
                {diag.last_run.status}
              </div>
              <StagePipeline stages={diag.last_run.stages} />
            </div>
          )}

          {/* Which companies still need financials. */}
          {missingFin.length > 0 && (
            <details style={{ marginTop: 6 }}>
              <summary style={{ cursor: "pointer", fontSize: 13 }}>
                Missing financials for {missingFin.length} compan
                {missingFin.length === 1 ? "y" : "ies"}
              </summary>
              <ul style={{ fontSize: 13, margin: "6px 0", paddingLeft: 18 }}>
                {missingFin.map((m) => (
                  <li key={m.ticker}>
                    <strong>{m.ticker}</strong>{" "}
                    <span style={{ color: "#64748b" }}>{m.name}</span> — needs{" "}
                    {m.missing.join(", ")}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {/* Run history. */}
          {diag.runs.length > 0 && (
            <details style={{ marginTop: 6 }}>
              <summary style={{ cursor: "pointer", fontSize: 13 }}>
                Run history ({diag.runs.length})
              </summary>
              <ul style={{ fontSize: 12, margin: "6px 0", paddingLeft: 18 }}>
                {diag.runs.map((r) => (
                  <li key={r.id} style={{ color: "#334155" }}>
                    {runLabel(r)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
