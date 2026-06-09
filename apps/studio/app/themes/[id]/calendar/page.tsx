"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyProgEvent,
  BlueprintProgress,
  type Prog,
} from "../../../../components/Progress";
import { useResumableRun } from "../../../../components/useResumableRun";
import { StepFooter } from "../../../../components/WorkflowSteps";
import {
  cancelTask,
  getCalendar,
  putCalendarEntry,
  researchCalendarStream,
  type CalendarEntryInput,
  type CalendarRow,
  type CveRunEvent,
} from "../../../../lib/api";

const EMPTY_PROG: Prog = { output: "", steps: [], done: false, running: false };

// Common filing cadences -> days. Admin picks one; the engine projects the next filing from
// last_filing_date + cadence when no explicit date is given.
const CADENCES = [
  { label: "Quarterly", days: 91 },
  { label: "Annual", days: 365 },
] as const;

type Draft = {
  last_filing_date: string;
  cadence_days: string; // "" | "91" | "365" | a researched median gap
  next_filing_estimate: string;
  source: string;
};

const EMPTY_DRAFT: Draft = {
  last_filing_date: "",
  cadence_days: "",
  next_filing_estimate: "",
  source: "",
};

function toDraft(row: CalendarRow): Draft {
  return {
    last_filing_date: row.last_filing_date ?? "",
    cadence_days: row.cadence_days != null ? String(row.cadence_days) : "",
    next_filing_estimate: row.next_filing_estimate ?? "",
    source: row.source ?? "",
  };
}

const str = (v: unknown): string | null =>
  typeof v === "number" ? String(v) : typeof v === "string" ? v : null;

const hostOf = (s: string): string => {
  try {
    return new URL(s).hostname.replace(/^www\./, "");
  } catch {
    return s;
  }
};

export default function CalendarPage() {
  const { id: themeId } = useParams<{ id: string }>();
  const [rows, setRows] = useState<CalendarRow[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [covered, setCovered] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [researching, setResearching] = useState(false);
  const [researchingTicker, setResearchingTicker] = useState<string | null>(
    null,
  );
  const [prog, setProg] = useState<Prog>(EMPTY_PROG);
  const panelRef = useRef<HTMLDivElement>(null);

  // The live panel sits at the top; per-company Research is down in the table — scroll the
  // panel into view when a run starts so its streaming progress is actually seen.
  useEffect(() => {
    if (prog.running)
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    else setResearchingTicker(null);
  }, [prog.running]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getCalendar(themeId);
      setRows(data.rows);
      setCovered(data.covered);
      setTotal(data.total);
      setDrafts(
        Object.fromEntries(data.rows.map((r) => [r.ticker, toDraft(r)])),
      );
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [themeId]);

  useEffect(() => {
    void load();
  }, [load]);

  function setField(ticker: string, key: keyof Draft, value: string) {
    setDrafts((d) => ({
      ...d,
      [ticker]: { ...(d[ticker] ?? EMPTY_DRAFT), [key]: value },
    }));
  }

  function onResearchEvent(e: CveRunEvent) {
    setProg((p) => applyProgEvent(p, e));
    if (e.event === "task") {
      const kind = String(e.kind ?? "");
      const prefix = "calendar-research:";
      setResearchingTicker(
        kind.startsWith(prefix) ? kind.slice(prefix.length) : null,
      );
    }
    if (e.event === "filled") {
      const t = String(e.ticker);
      setDrafts((d) => {
        const cur = d[t] ?? EMPTY_DRAFT;
        return {
          ...d,
          [t]: {
            last_filing_date: str(e.last_filing_date) ?? cur.last_filing_date,
            cadence_days: str(e.cadence_days) ?? cur.cadence_days,
            next_filing_estimate:
              str(e.next_filing_estimate) ?? cur.next_filing_estimate,
            source: str(e.source) ?? cur.source,
          },
        };
      });
      setProg((p) => ({
        ...p,
        steps: [
          ...p.steps,
          {
            label: `filled ${t}`,
            detail:
              `next ${e.next_filing_estimate ?? "—"} · cadence ${e.cadence_days ?? "—"}d` +
              (e.source ? ` · src ${hostOf(String(e.source))}` : ""),
            tone: "ok",
          },
        ],
      }));
    }
    if (e.event === "skipped") {
      setProg((p) => ({
        ...p,
        steps: [
          ...p.steps,
          {
            label: `skipped ${String(e.ticker)}`,
            detail: String(e.reason ?? "no filing dates found"),
            tone: "warn",
          },
        ],
      }));
    }
  }

  // `tickers` undefined -> research all; a single-element array -> just that company.
  async function onResearch(tickers?: string[]) {
    setResearching(true);
    if (tickers?.length === 1) setResearchingTicker(tickers[0]);
    setProg({ ...EMPTY_PROG, running: true });
    try {
      await researchCalendarStream(themeId, onResearchEvent, tickers);
      await load(); // research persists server-side; reconcile rows + coverage
    } catch (e) {
      setProg((p) => ({ ...p, running: false, error: String(e) }));
    } finally {
      setResearching(false);
      setResearchingTicker(null);
    }
  }

  // Resume a calendar research already running for this theme (incl. per-company sub-kinds).
  const { resuming } = useResumableRun(
    themeId,
    ["calendar-research"],
    onResearchEvent,
  );
  const busy = researching || resuming;

  async function onSave(ticker: string) {
    const d = drafts[ticker] ?? EMPTY_DRAFT;
    setSaving(ticker);
    try {
      const body: CalendarEntryInput = {
        last_filing_date: d.last_filing_date || null,
        cadence_days: d.cadence_days ? Number(d.cadence_days) : null,
        next_filing_estimate: d.next_filing_estimate || null,
        source: d.source || null,
      };
      const updated = await putCalendarEntry(themeId, ticker, body);
      setRows((prev) => {
        const next = prev.map((r) => (r.ticker === ticker ? updated : r));
        setCovered(next.filter((r) => r.covered).length);
        return next;
      });
      setDrafts((m) => ({ ...m, [ticker]: toDraft(updated) }));
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(null);
    }
  }

  const coveredOf = (t: string) =>
    rows.find((r) => r.ticker === t)?.covered ?? false;

  return (
    <section>
      <h2 style={{ marginBottom: 4 }}>Disclosure Calendar</h2>
      <p style={{ color: "#475569", marginTop: 0 }}>
        <small>
          Each company&apos;s next filing date drives every edge&apos;s{" "}
          <strong>next_expected_update</strong> — a required field. Without it
          an edge can&apos;t be published as a verified figure and is drawn as a
          gap. Deep Research the filing history to infer cadence automatically,
          or set it by hand. Takes effect on the next build.
        </small>
      </p>

      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          margin: "8px 0",
        }}
      >
        <button
          type="button"
          onClick={() => void onResearch()}
          disabled={busy || rows.length === 0}
        >
          {researching && !researchingTicker
            ? "Researching…"
            : "🔍 Research all filing dates"}
        </button>
        <strong>
          {covered}/{total}
        </strong>{" "}
        <small style={{ color: covered === total ? "#15803d" : "#b45309" }}>
          companies have a next-filing date
        </small>
      </div>

      <div ref={panelRef}>
        <BlueprintProgress
          prog={prog}
          markdown
          onStop={(id) => void cancelTask(id)}
          labels={{
            running: researchingTicker
              ? `Researching ${researchingTicker}'s filing history…`
              : "Researching filing dates…",
            done: "Filing dates researched",
            idle: "Calendar research",
          }}
        />
      </div>

      {error && (
        <p style={{ color: "crimson" }}>
          <small>Couldn&apos;t load: {error}</small>{" "}
          <button type="button" onClick={() => void load()}>
            Retry
          </button>
        </p>
      )}

      {loading ? (
        <p>
          <small>Loading…</small>
        </p>
      ) : rows.length === 0 ? (
        <p>
          <small>No companies yet — generate/approve a blueprint first.</small>
        </p>
      ) : (
        <table
          style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}
        >
          <thead>
            <tr style={{ textAlign: "left", color: "#64748b", fontSize: 12 }}>
              <th style={{ padding: "4px 6px" }}>Company</th>
              <th style={{ padding: "4px 6px" }}>Last filing</th>
              <th style={{ padding: "4px 6px" }}>Cadence</th>
              <th style={{ padding: "4px 6px" }}>Next filing</th>
              <th style={{ padding: "4px 6px" }}>Source</th>
              <th style={{ padding: "4px 6px" }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const d = drafts[row.ticker] ?? EMPTY_DRAFT;
              const knownCadence =
                d.cadence_days === "" ||
                CADENCES.some((c) => String(c.days) === d.cadence_days);
              return (
                <tr key={row.ticker} style={{ borderTop: "1px solid #e2e8f0" }}>
                  <td style={{ padding: "8px 6px", whiteSpace: "nowrap" }}>
                    <span title={coveredOf(row.ticker) ? "covered" : "missing"}>
                      {coveredOf(row.ticker) ? "🟢" : "🟠"}
                    </span>{" "}
                    <strong>{row.ticker}</strong>
                    <div style={{ fontSize: 12, color: "#64748b" }}>
                      {row.name}
                    </div>
                  </td>
                  <td style={{ padding: "8px 6px" }}>
                    <input
                      type="date"
                      value={d.last_filing_date}
                      onChange={(e) =>
                        setField(row.ticker, "last_filing_date", e.target.value)
                      }
                    />
                  </td>
                  <td style={{ padding: "8px 6px" }}>
                    <select
                      value={knownCadence ? d.cadence_days : ""}
                      onChange={(e) =>
                        setField(row.ticker, "cadence_days", e.target.value)
                      }
                    >
                      <option value="">—</option>
                      {CADENCES.map((c) => (
                        <option key={c.days} value={c.days}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                    {!knownCadence && (
                      <div style={{ fontSize: 11, color: "#64748b" }}>
                        ~{d.cadence_days}d
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "8px 6px" }}>
                    <input
                      type="date"
                      value={d.next_filing_estimate}
                      onChange={(e) =>
                        setField(
                          row.ticker,
                          "next_filing_estimate",
                          e.target.value,
                        )
                      }
                      title="Set explicitly, or leave blank to compute from last filing + cadence"
                    />
                  </td>
                  <td style={{ padding: "8px 6px" }}>
                    <input
                      placeholder="IR / disclosure page"
                      value={d.source}
                      onChange={(e) =>
                        setField(row.ticker, "source", e.target.value)
                      }
                      style={{ width: 150 }}
                    />
                  </td>
                  <td
                    style={{
                      padding: "8px 6px",
                      whiteSpace: "nowrap",
                      display: "flex",
                      gap: 6,
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => void onSave(row.ticker)}
                      disabled={saving === row.ticker}
                    >
                      {saving === row.ticker ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void onResearch([row.ticker])}
                      disabled={busy}
                      title="Deep Research this company's filing history"
                    >
                      🔍
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <StepFooter themeId={themeId} currentKey="calendar" />
    </section>
  );
}
