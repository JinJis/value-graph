"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  generateTickets,
  listTickets,
  listTicketSources,
  sourceContentUrl,
  uploadTicketEvidence,
  type Source,
  type Ticket,
} from "../../../../lib/api";

const STATUS_OPTIONS = ["all", "OPEN", "SUBMITTED", "UNRESOLVABLE", "DEFERRED"];
const SOURCE_TYPES = ["filing", "IR", "report", "news", "interview"];
const SORT_OPTIONS = [
  "priority",
  "target",
  "metric",
  "status",
  "created",
] as const;
type SortKey = (typeof SORT_OPTIONS)[number];

function compare(a: Ticket, b: Ticket, key: SortKey): number {
  switch (key) {
    case "target":
      return a.target.localeCompare(b.target);
    case "metric":
      return a.metric.localeCompare(b.metric);
    case "status":
      return a.status.localeCompare(b.status);
    case "created":
      return a.created_at.localeCompare(b.created_at);
    case "priority": {
      // OPEN first, then oldest first.
      const rank = (t: Ticket) => (t.status === "OPEN" ? 0 : 1);
      return rank(a) - rank(b) || a.created_at.localeCompare(b.created_at);
    }
  }
}

export default function TicketQueuePage() {
  const params = useParams<{ id: string }>();
  const themeId = params.id;

  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [target, setTarget] = useState("");
  const [metric, setMetric] = useState("");
  const [status, setStatus] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [genMsg, setGenMsg] = useState<string | null>(null);

  // Evidence upload (for the selected ticket).
  const [evSources, setEvSources] = useState<Source[]>([]);
  const [evFile, setEvFile] = useState<File | null>(null);
  const [evUrl, setEvUrl] = useState("");
  const [evType, setEvType] = useState("filing");
  const [evPublisher, setEvPublisher] = useState("");
  const [evAsOf, setEvAsOf] = useState("");

  async function load() {
    try {
      setTickets(await listTickets(themeId));
      setError(null);
    } catch (e) {
      setError(`Load failed: ${String(e)}`);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeId]);

  async function loadEvidence(ticketId: string) {
    try {
      setEvSources(await listTicketSources(ticketId));
    } catch {
      setEvSources([]);
    }
  }

  useEffect(() => {
    if (selected) void loadEvidence(selected.id);
    else setEvSources([]);
  }, [selected]);

  async function onUploadEvidence() {
    if (!selected) return;
    if (!evFile && !evUrl.trim()) {
      setError("Provide a file or a URL");
      return;
    }
    setBusy(true);
    try {
      await uploadTicketEvidence(selected.id, {
        file: evFile ?? undefined,
        url: evUrl.trim() || undefined,
        type: evType,
        publisher: evPublisher.trim() || undefined,
        as_of_date: evAsOf || undefined,
      });
      setEvFile(null);
      setEvUrl("");
      setEvPublisher("");
      setEvAsOf("");
      await load(); // ticket status -> SUBMITTED
      await loadEvidence(selected.id);
      setSelected((s) => (s ? { ...s, status: "SUBMITTED" } : s));
      setError(null);
    } catch (e) {
      setError(`Upload failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function onGenerate() {
    setBusy(true);
    try {
      const r = await generateTickets(themeId);
      setGenMsg(`Generated ${r.created}, skipped ${r.skipped}`);
      await load();
      setError(null);
    } catch (e) {
      setError(`Generate failed (is the blueprint approved?): ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const visible = useMemo(() => {
    const t = target.trim().toLowerCase();
    const m = metric.trim().toLowerCase();
    return tickets
      .filter((x) => status === "all" || x.status === status)
      .filter((x) => !t || x.target.toLowerCase().includes(t))
      .filter((x) => !m || x.metric.toLowerCase().includes(m))
      .slice()
      .sort((a, b) => compare(a, b, sortKey));
  }, [tickets, target, metric, status, sortKey]);

  return (
    <main
      style={{ maxWidth: 1000, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <p>
        <Link href={`/themes/${themeId}`}>← Theme</Link>
      </p>
      <h1>Ticket queue</h1>

      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          margin: "1rem 0",
        }}
      >
        <button type="button" onClick={onGenerate} disabled={busy}>
          Generate tickets
        </button>
        {genMsg && <small>{genMsg}</small>}
      </div>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <div
        style={{
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          margin: "0.5rem 0",
        }}
      >
        <input
          placeholder="Filter company/target…"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        />
        <input
          placeholder="Filter metric…"
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
        />
        <label>
          Status:{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sort:{" "}
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
          >
            {SORT_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p>
        <small>
          {visible.length} of {tickets.length} tickets
        </small>
      </p>

      <table
        style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}
      >
        <thead>
          <tr>
            {["target", "metric", "status", "reason"].map((h) => (
              <th
                key={h}
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #ccc",
                  padding: 6,
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((t) => (
            <tr
              key={t.id}
              onClick={() => setSelected(t)}
              style={{
                cursor: "pointer",
                background: selected?.id === t.id ? "#eef" : undefined,
              }}
            >
              <td style={{ padding: 6 }}>{t.target}</td>
              <td style={{ padding: 6 }}>{t.metric}</td>
              <td style={{ padding: 6 }}>{t.status}</td>
              <td style={{ padding: 6 }}>{t.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length === 0 && <p>No tickets match.</p>}

      {selected && (
        <div
          style={{
            marginTop: 24,
            padding: 16,
            border: "1px solid #ccc",
            borderRadius: 6,
          }}
        >
          <h2 style={{ marginTop: 0 }}>Ticket detail</h2>
          <p>
            <strong>Requested:</strong> {selected.metric} for {selected.target}
          </p>
          <p>
            <strong>Why:</strong> {selected.reason ?? "—"}
          </p>
          <p>
            <small>
              status: {selected.status}
              {selected.reason_code
                ? ` · reason: ${selected.reason_code}`
                : ""}{" "}
              · created: {selected.created_at}
            </small>
          </p>
          {selected.current_estimate && (
            <pre style={{ background: "#f6f6f6", padding: 8 }}>
              {JSON.stringify(selected.current_estimate, null, 2)}
            </pre>
          )}

          <h3>Upload evidence → Source</h3>
          <div style={{ display: "grid", gap: 6, maxWidth: 520 }}>
            <input
              type="file"
              onChange={(e) => setEvFile(e.target.files?.[0] ?? null)}
            />
            <input
              placeholder="…or a source URL (DART/EDGAR/news)"
              value={evUrl}
              onChange={(e) => setEvUrl(e.target.value)}
            />
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <select
                value={evType}
                onChange={(e) => setEvType(e.target.value)}
              >
                {SOURCE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <input
                placeholder="Publisher"
                value={evPublisher}
                onChange={(e) => setEvPublisher(e.target.value)}
              />
              <label>
                as-of:{" "}
                <input
                  type="date"
                  value={evAsOf}
                  onChange={(e) => setEvAsOf(e.target.value)}
                />
              </label>
              <button type="button" onClick={onUploadEvidence} disabled={busy}>
                Submit evidence
              </button>
            </div>
          </div>

          <h4>Evidence ({evSources.length})</h4>
          {evSources.length === 0 ? (
            <p>
              <small>No evidence yet.</small>
            </p>
          ) : (
            <ul>
              {evSources.map((s) => (
                <li key={s.id}>
                  <a
                    href={s.url ?? sourceContentUrl(s)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {s.original_filename ?? s.url ?? s.id}
                  </a>{" "}
                  <small>
                    ({s.type}
                    {s.as_of_date ? ` · as of ${s.as_of_date}` : ""})
                  </small>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </main>
  );
}
