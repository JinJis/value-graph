"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  dismissTicketProposal,
  generateTickets,
  listTickets,
  listTicketEvents,
  listTicketSources,
  researchTicketsStream,
  resolveTicket,
  sourceContentUrl,
  uploadTicketEvidence,
  type Source,
  type Ticket,
  type TicketEvent,
  type TicketResearchEvent,
} from "../../../../lib/api";
import { BlueprintProgress, type Prog } from "../../../../components/Progress";

const EMPTY_PROG: Prog = { output: "", steps: [], done: false, running: false };

// Per-ticket result of a Deep Research batch, shown in the run summary.
interface TicketOutcome {
  ticketId: string;
  target: string;
  metric: string;
  kind: "running" | "proposed" | "auto_resolved" | "skipped" | "error";
  detail?: string;
}

const OUTCOME_LABEL: Record<TicketOutcome["kind"], string> = {
  running: "researching…",
  proposed: "proposal ready (review)",
  auto_resolved: "auto-resolved",
  skipped: "skipped",
  error: "error",
};

// The found answer awaiting the admin's accept/reject. Accept attaches the cited URL as
// evidence (-> SUBMITTED); reject clears it.
function ProposalCard({
  ticket,
  busy,
  onAccept,
  onReject,
}: {
  ticket: Ticket;
  busy: boolean;
  onAccept: (t: Ticket) => void;
  onReject: (t: Ticket) => void;
}) {
  const p = ticket.research_proposal;
  if (!p) return null;
  return (
    <div
      style={{
        border: "1px solid #16a34a",
        background: "#f0fdf4",
        borderRadius: 6,
        padding: 12,
        margin: "8px 0",
      }}
    >
      <strong style={{ color: "#15803d" }}>
        Deep Research found an answer
      </strong>
      <div style={{ fontSize: 14, marginTop: 4 }}>
        <div>
          <strong>{String(p.value ?? "—")}</strong>
          {p.unit ? ` ${p.unit}` : ""}
          {p.confidence ? ` · ${p.confidence} confidence` : ""}
        </div>
        {p.as_of_date && (
          <div>
            <small>as of {p.as_of_date}</small>
          </div>
        )}
        {p.source_url && (
          <div>
            <a href={p.source_url} target="_blank" rel="noreferrer">
              {p.source_publisher ?? p.source_url}
            </a>
          </div>
        )}
        {p.notes && (
          <div>
            <small>{p.notes}</small>
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button
          type="button"
          onClick={() => onAccept(ticket)}
          disabled={busy || !p.source_url}
        >
          Accept → attach source
        </button>
        <button type="button" onClick={() => onReject(ticket)} disabled={busy}>
          Reject
        </button>
      </div>
    </div>
  );
}

const STATUS_OPTIONS = [
  "all",
  "OPEN",
  "SUBMITTED",
  "UNRESOLVABLE",
  "DEFERRED",
  "CLOSED",
];
const SOURCE_TYPES = ["filing", "IR", "report", "news", "interview"];
const REASON_CODES = ["not-found", "not-disclosed", "paywalled", "ambiguous"];
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

  // Deep Research batch: multi-select + live streaming panel + per-ticket outcomes.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [researching, setResearching] = useState(false);
  const [showPanel, setShowPanel] = useState(true);
  const [prog, setProg] = useState<Prog>(EMPTY_PROG);
  const [active, setActive] = useState<{
    target: string;
    metric: string;
  } | null>(null);
  const [outcomes, setOutcomes] = useState<TicketOutcome[]>([]);

  // Evidence upload (for the selected ticket).
  const [evSources, setEvSources] = useState<Source[]>([]);
  const [evFile, setEvFile] = useState<File | null>(null);
  const [evUrl, setEvUrl] = useState("");
  const [evType, setEvType] = useState("filing");
  const [evPublisher, setEvPublisher] = useState("");
  const [evAsOf, setEvAsOf] = useState("");
  const [resReason, setResReason] = useState("not-disclosed");
  const [events, setEvents] = useState<TicketEvent[]>([]);

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

  async function loadTicketDetail(ticketId: string) {
    try {
      const [sources, history] = await Promise.all([
        listTicketSources(ticketId),
        listTicketEvents(ticketId),
      ]);
      setEvSources(sources);
      setEvents(history);
    } catch {
      setEvSources([]);
      setEvents([]);
    }
  }

  useEffect(() => {
    if (selected) {
      void loadTicketDetail(selected.id);
    } else {
      setEvSources([]);
      setEvents([]);
    }
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
      await loadTicketDetail(selected.id);
      setSelected((s) => (s ? { ...s, status: "SUBMITTED" } : s));
      setError(null);
    } catch (e) {
      setError(`Upload failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function onResolve(status: "UNRESOLVABLE" | "DEFERRED") {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await resolveTicket(selected.id, status, resReason);
      setSelected(updated);
      await load();
      await loadTicketDetail(updated.id);
      setError(null);
    } catch (e) {
      setError(`Resolve failed: ${String(e)}`);
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

  function toggleOne(id: string, on: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function upsertOutcome(ticketId: string, patch: Partial<TicketOutcome>) {
    setOutcomes((prev) => {
      const i = prev.findIndex((o) => o.ticketId === ticketId);
      if (i === -1) {
        return [
          ...prev,
          { ticketId, target: "", metric: "", kind: "running", ...patch },
        ];
      }
      const next = prev.slice();
      next[i] = { ...next[i], ...patch };
      return next;
    });
  }

  // Fold one SSE frame into the live panel (current ticket) + the outcome summary.
  function onResearchEvent(e: TicketResearchEvent) {
    const tid = typeof e.ticket_id === "string" ? e.ticket_id : undefined;
    switch (e.event) {
      case "model":
        setProg((p) => ({
          ...p,
          model: { tier: String(e.tier), model: String(e.model) },
        }));
        break;
      case "endpoint":
        setProg((p) => ({
          ...p,
          endpoint: { provider: String(e.provider), method: String(e.method) },
        }));
        break;
      case "ticket_start":
        setActive({ target: String(e.target), metric: String(e.metric) });
        setProg((p) => ({
          ...EMPTY_PROG,
          model: p.model,
          endpoint: p.endpoint,
          running: true,
        }));
        if (tid)
          upsertOutcome(tid, {
            target: String(e.target),
            metric: String(e.metric),
            kind: "running",
          });
        break;
      case "prompt":
        setProg((p) => ({ ...p, prompt: String(e.text) }));
        break;
      case "llm_start":
        setProg((p) => ({ ...p, output: "" }));
        break;
      case "chunk":
        setProg((p) => ({ ...p, output: p.output + String(e.text ?? "") }));
        break;
      case "thought":
        setProg((p) => ({
          ...p,
          steps: [...p.steps, { label: "thinking", detail: String(e.text) }],
        }));
        break;
      case "research":
        setProg((p) => ({
          ...p,
          steps: [
            ...p.steps,
            { label: String(e.action), detail: String(e.detail) },
          ],
        }));
        break;
      case "parse":
        setProg((p) => ({
          ...p,
          steps: [
            ...p.steps,
            {
              label: "parse",
              detail: String(e.status),
              tone: e.status === "ok" ? "ok" : "warn",
            },
          ],
        }));
        break;
      case "proposed":
        if (tid)
          upsertOutcome(tid, {
            kind: "proposed",
            detail: String(e.value ?? ""),
          });
        setProg((p) => ({
          ...p,
          steps: [
            ...p.steps,
            {
              label: "proposal ready",
              detail: String(e.value ?? ""),
              tone: "ok",
            },
          ],
        }));
        break;
      case "auto_resolved":
        if (tid)
          upsertOutcome(tid, {
            kind: "auto_resolved",
            detail: `${e.status} · ${e.reason_code}`,
          });
        setProg((p) => ({
          ...p,
          steps: [
            ...p.steps,
            {
              label: "auto-resolved",
              detail: `${e.status} · ${e.reason_code}`,
              tone: "warn",
            },
          ],
        }));
        break;
      case "skipped":
        if (tid)
          upsertOutcome(tid, {
            kind: "skipped",
            detail: String(e.detail ?? ""),
          });
        break;
      case "error":
        if (tid)
          upsertOutcome(tid, { kind: "error", detail: String(e.detail ?? "") });
        setProg((p) => ({
          ...p,
          error: String(e.detail ?? "research error"),
          running: false,
        }));
        break;
      case "done":
        setProg((p) => ({ ...p, running: false, done: true }));
        break;
    }
  }

  async function onRunResearch() {
    if (selectedIds.size === 0) return;
    setResearching(true);
    setShowPanel(true);
    setActive(null);
    setOutcomes([]);
    setProg({ ...EMPTY_PROG, running: true });
    try {
      await researchTicketsStream(
        themeId,
        Array.from(selectedIds),
        onResearchEvent,
      );
      const fresh = await listTickets(themeId);
      setTickets(fresh);
      setSelected((s) => (s ? (fresh.find((x) => x.id === s.id) ?? null) : s));
      setError(null);
    } catch (e) {
      setError(`Research failed: ${String(e)}`);
      setProg((p) => ({ ...p, running: false, error: String(e) }));
    } finally {
      setResearching(false);
    }
  }

  async function onAcceptProposal(t: Ticket) {
    const p = t.research_proposal;
    if (!p?.source_url) return;
    setBusy(true);
    try {
      await uploadTicketEvidence(t.id, {
        url: p.source_url,
        type: "report",
        publisher: p.source_publisher ?? undefined,
        as_of_date: p.as_of_date ?? undefined,
      });
      const fresh = await listTickets(themeId);
      setTickets(fresh);
      setSelected((s) => (s ? (fresh.find((x) => x.id === s.id) ?? null) : s));
      if (selected?.id === t.id) await loadTicketDetail(t.id);
      setError(null);
    } catch (e) {
      setError(`Accept failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function onRejectProposal(t: Ticket) {
    setBusy(true);
    try {
      await dismissTicketProposal(t.id);
      const fresh = await listTickets(themeId);
      setTickets(fresh);
      setSelected((s) => (s ? (fresh.find((x) => x.id === s.id) ?? null) : s));
      setError(null);
    } catch (e) {
      setError(`Reject failed: ${String(e)}`);
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

      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          margin: "0.5rem 0",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          onClick={onRunResearch}
          disabled={researching || busy || selectedIds.size === 0}
        >
          {researching
            ? "Researching…"
            : `Run Deep Research (${selectedIds.size})`}
        </button>
        <label style={{ fontSize: 13 }}>
          <input
            type="checkbox"
            checked={showPanel}
            onChange={(e) => setShowPanel(e.target.checked)}
          />{" "}
          live panel
        </label>
        <small style={{ color: "#64748b" }}>
          Found → review &amp; accept · not found → auto-resolved.
        </small>
      </div>

      {showPanel && (researching || outcomes.length > 0 || !!prog.model) && (
        <div style={{ margin: "0.5rem 0" }}>
          {active && (
            <p style={{ fontSize: 13, margin: "4px 0" }}>
              Researching <strong>{active.metric}</strong> for{" "}
              <strong>{active.target}</strong>
            </p>
          )}
          <BlueprintProgress prog={prog} />
          {outcomes.length > 0 && (
            <ul style={{ fontSize: 13, paddingLeft: 18 }}>
              {outcomes.map((o) => (
                <li key={o.ticketId}>
                  <strong>{o.target}</strong> · {o.metric} —{" "}
                  {OUTCOME_LABEL[o.kind]}
                  {o.detail ? `: ${o.detail}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

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
            <th
              style={{
                textAlign: "left",
                borderBottom: "1px solid #ccc",
                padding: 6,
                width: 32,
              }}
            >
              <input
                type="checkbox"
                aria-label="select all"
                checked={
                  visible.length > 0 &&
                  visible.every((t) => selectedIds.has(t.id))
                }
                onChange={(e) => {
                  const on = e.target.checked;
                  setSelectedIds((prev) => {
                    const next = new Set(prev);
                    for (const t of visible) {
                      if (on) next.add(t.id);
                      else next.delete(t.id);
                    }
                    return next;
                  });
                }}
              />
            </th>
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
              <td style={{ padding: 6 }} onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  aria-label={`select ${t.target}`}
                  checked={selectedIds.has(t.id)}
                  onChange={(e) => toggleOne(t.id, e.target.checked)}
                />
              </td>
              <td style={{ padding: 6 }}>{t.target}</td>
              <td style={{ padding: 6 }}>{t.metric}</td>
              <td style={{ padding: 6 }}>
                {t.status}
                {t.research_proposal ? (
                  <span
                    style={{ marginLeft: 6, color: "#15803d", fontSize: 12 }}
                    title="Deep Research proposal awaiting review"
                  >
                    ● proposal
                  </span>
                ) : null}
              </td>
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

          <ProposalCard
            ticket={selected}
            busy={busy}
            onAccept={onAcceptProposal}
            onReject={onRejectProposal}
          />

          <h3>Cannot resolve?</h3>
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            reason:
            <select
              value={resReason}
              onChange={(e) => setResReason(e.target.value)}
            >
              {REASON_CODES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => onResolve("UNRESOLVABLE")}
              disabled={busy}
            >
              Mark unresolvable
            </button>
            <button
              type="button"
              onClick={() => onResolve("DEFERRED")}
              disabled={busy}
            >
              Defer
            </button>
            <small>not-disclosed records the ≤10% upper bound for CVE.</small>
          </div>

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

          <h4>History ({events.length})</h4>
          <ul style={{ fontSize: 13 }}>
            {events.map((e) => (
              <li key={e.id}>
                {e.from_status ?? "—"} → <strong>{e.to_status}</strong>
                {e.reason_code ? ` (${e.reason_code})` : ""} · {e.actor} ·{" "}
                {e.created_at}
              </li>
            ))}
          </ul>
        </div>
      )}
    </main>
  );
}
