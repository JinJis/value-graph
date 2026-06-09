"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { StepFooter } from "../../../../components/WorkflowSteps";
import {
  getCalendar,
  putCalendarEntry,
  type CalendarRow,
  type CalendarEntryInput,
} from "../../../../lib/api";

// Common filing cadences -> days. Admin picks one; the engine projects the next filing from
// last_filing_date + cadence when no explicit date is given.
const CADENCES = [
  { label: "Quarterly", days: 91 },
  { label: "Annual", days: 365 },
] as const;

type Draft = {
  last_filing_date: string;
  cadence_days: string; // "" | "91" | "365"
  next_filing_estimate: string;
  source: string;
};

function toDraft(row: CalendarRow): Draft {
  return {
    last_filing_date: row.last_filing_date ?? "",
    cadence_days: row.cadence_days != null ? String(row.cadence_days) : "",
    next_filing_estimate: row.next_filing_estimate ?? "",
    source: row.source ?? "",
  };
}

function CalendarRowEditor({
  themeId,
  row,
  onSaved,
}: {
  themeId: string;
  row: CalendarRow;
  onSaved: (updated: CalendarRow) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(row));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof Draft, v: string) =>
    setDraft((d) => ({ ...d, [k]: v }));

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body: CalendarEntryInput = {
        last_filing_date: draft.last_filing_date || null,
        cadence_days: draft.cadence_days ? Number(draft.cadence_days) : null,
        next_filing_estimate: draft.next_filing_estimate || null,
        source: draft.source || null,
      };
      onSaved(await putCalendarEntry(themeId, row.ticker, body));
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr style={{ borderTop: "1px solid #e2e8f0" }}>
      <td style={{ padding: "8px 6px", whiteSpace: "nowrap" }}>
        <span title={row.covered ? "covered" : "missing next filing"}>
          {row.covered ? "🟢" : "🟠"}
        </span>{" "}
        <strong>{row.ticker}</strong>
        <div style={{ fontSize: 12, color: "#64748b" }}>{row.name}</div>
      </td>
      <td style={{ padding: "8px 6px" }}>
        <input
          type="date"
          value={draft.last_filing_date}
          onChange={(e) => set("last_filing_date", e.target.value)}
        />
      </td>
      <td style={{ padding: "8px 6px" }}>
        <select
          value={draft.cadence_days}
          onChange={(e) => set("cadence_days", e.target.value)}
        >
          <option value="">—</option>
          {CADENCES.map((c) => (
            <option key={c.days} value={c.days}>
              {c.label}
            </option>
          ))}
        </select>
      </td>
      <td style={{ padding: "8px 6px" }}>
        <input
          type="date"
          value={draft.next_filing_estimate}
          onChange={(e) => set("next_filing_estimate", e.target.value)}
          title="Set explicitly, or leave blank to compute from last filing + cadence"
        />
      </td>
      <td style={{ padding: "8px 6px" }}>
        <input
          placeholder="e.g. investor-relations page"
          value={draft.source}
          onChange={(e) => set("source", e.target.value)}
          style={{ width: 160 }}
        />
      </td>
      <td style={{ padding: "8px 6px" }}>
        <button type="button" onClick={() => void save()} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {error && <div style={{ color: "crimson", fontSize: 12 }}>{error}</div>}
      </td>
    </tr>
  );
}

export default function CalendarPage() {
  const { id: themeId } = useParams<{ id: string }>();
  const [rows, setRows] = useState<CalendarRow[]>([]);
  const [covered, setCovered] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getCalendar(themeId);
      setRows(data.rows);
      setCovered(data.covered);
      setTotal(data.total);
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

  function onSaved(updated: CalendarRow) {
    setRows((prev) => {
      const next = prev.map((r) => (r.ticker === updated.ticker ? updated : r));
      setCovered(next.filter((r) => r.covered).length);
      return next;
    });
  }

  return (
    <section>
      <h2 style={{ marginBottom: 4 }}>Disclosure Calendar</h2>
      <p style={{ color: "#475569", marginTop: 0 }}>
        <small>
          Each company&apos;s next filing date drives every edge&apos;s{" "}
          <strong>next_expected_update</strong> — a required field. Without it
          an edge can&apos;t be published as a verified figure and is drawn as a
          gap. Set the next filing directly, or give the last filing + cadence
          and the engine projects it. Takes effect on the next build.
        </small>
      </p>

      <p style={{ margin: "8px 0" }}>
        <strong>
          {covered}/{total}
        </strong>{" "}
        <small style={{ color: covered === total ? "#15803d" : "#b45309" }}>
          companies have a next-filing date
        </small>
      </p>

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
            {rows.map((row) => (
              <CalendarRowEditor
                key={row.ticker}
                themeId={themeId}
                row={row}
                onSaved={onSaved}
              />
            ))}
          </tbody>
        </table>
      )}

      <StepFooter themeId={themeId} currentKey="calendar" />
    </section>
  );
}
