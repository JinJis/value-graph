// Minimal client for the ValueGraph Engine API.
// Calls go to this app's OWN origin under "/engine", which Next.js rewrites server-side
// to the engine (see next.config.mjs). The browser never needs the engine's port, so it
// works behind any tunnel/proxy with no CORS. NEXT_PUBLIC_ENGINE_URL overrides if needed.
function engineUrl(): string {
  return process.env.NEXT_PUBLIC_ENGINE_URL ?? "/engine";
}

export interface Theme {
  id: string;
  name: string;
  version: number;
  status: string;
  description: string | null;
  seed_tickers: string[];
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Source {
  id: string;
  theme_id: string;
  ticket_id: string | null;
  type: string;
  publisher: string | null;
  as_of_date: string | null;
  language: string | null;
  url: string | null;
  verification_status: string;
  original_filename: string | null;
  content_type: string | null;
  created_at: string;
  content_url: string;
}

export interface DataQuality {
  verified: number;
  derived: number;
  estimated: number;
  gap: number;
}

export interface QualityReport {
  theme_id: string;
  snapshot_version: number;
  total: number;
  counts: {
    verified: number;
    derived: number;
    estimated: number;
    gap: number;
  };
  quality: DataQuality;
}

const url = (path: string): string => `${engineUrl()}${path}`;

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    // Surface the engine's real cause: FastAPI returns {"detail": "..."} (our
    // catch-all puts the exception type + message there). Fall back to raw text,
    // then to the status line, so the UI never just says "500".
    let detail = "";
    try {
      const body = await response.clone().json();
      detail =
        typeof body?.detail === "string"
          ? body.detail
          : body?.detail
            ? JSON.stringify(body.detail)
            : "";
    } catch {
      try {
        detail = (await response.text()).slice(0, 500);
      } catch {
        detail = "";
      }
    }
    const head = `${response.status} ${response.statusText}`.trim();
    throw new Error(detail ? `${head} — ${detail}` : head);
  }
  return response.json() as Promise<T>;
}

export async function listThemes(): Promise<Theme[]> {
  return json(await fetch(url("/themes"), { cache: "no-store" }));
}

export async function getTheme(id: string): Promise<Theme> {
  return json(await fetch(url(`/themes/${id}`), { cache: "no-store" }));
}

export async function createTheme(input: {
  name: string;
  description?: string;
  seed_tickers?: string[];
}): Promise<Theme> {
  return json(
    await fetch(url("/themes"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
}

export async function listSources(themeId: string): Promise<Source[]> {
  return json(
    await fetch(url(`/themes/${themeId}/sources`), { cache: "no-store" }),
  );
}

export async function uploadSource(
  themeId: string,
  file: File,
  type: string,
  publisher?: string,
): Promise<Source> {
  const form = new FormData();
  form.append("file", file);
  form.append("type", type);
  if (publisher) form.append("publisher", publisher);
  return json(
    await fetch(url(`/themes/${themeId}/sources`), {
      method: "POST",
      body: form,
    }),
  );
}

export const sourceContentUrl = (source: Source): string =>
  url(source.content_url);

// --- Blueprint ---

export interface BlueprintCompany {
  ticker: string;
  name: string;
  country: string;
  exchange: string | null;
  role: string;
  products: string[];
  required_data_points: string[];
  source_url: string | null;
}

export interface BlueprintRecord {
  id: string;
  theme_id: string;
  version: number;
  generated_by: string | null;
  companies: BlueprintCompany[];
  relationship_types: string[];
  notes: string | null;
  created_at: string;
}

export interface Coverage {
  company_count: number;
  focus_countries: string[];
  meets_threshold: boolean;
}

export interface BlueprintResponse {
  blueprint: BlueprintRecord;
  coverage: Coverage;
}

export interface BlueprintContentInput {
  companies: BlueprintCompany[];
  relationship_types: string[];
  notes: string | null;
}

export async function getBlueprint(
  themeId: string,
): Promise<BlueprintResponse | null> {
  const response = await fetch(url(`/themes/${themeId}/blueprint`), {
    cache: "no-store",
  });
  if (response.status === 404) return null;
  return json(response);
}

export async function saveBlueprint(
  themeId: string,
  content: BlueprintContentInput,
): Promise<BlueprintResponse> {
  return json(
    await fetch(url(`/themes/${themeId}/blueprint`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(content),
    }),
  );
}

export async function generateBlueprint(
  themeId: string,
): Promise<BlueprintResponse> {
  return json(
    await fetch(url(`/themes/${themeId}/blueprint`), { method: "POST" }),
  );
}

// A single progress event from the streaming blueprint endpoint. `event` names the
// step (model / endpoint / prompt / llm_start / thought / research / chunk / parse /
// sources / validate / saved / error / done); other fields depend on the step (see
// engine blueprint/stream.py). thought/research come from the Deep Research agent.
export interface BlueprintEvent {
  event: string;
  [key: string]: unknown;
}

// POST `path` and parse the Server-Sent Events response, invoking `onEvent` per frame.
// Uses a streaming fetch (not EventSource, which can't POST) and frames the SSE bytes
// manually. An optional JSON `body` is sent for endpoints that need a payload (e.g. the
// list of ticket ids to research). Shared by the blueprint and ticket-research streams.
async function postEventStream<E = BlueprintEvent>(
  path: string,
  onEvent: (event: E) => void,
  signal?: AbortSignal,
  body?: unknown,
): Promise<void> {
  const response = await fetch(url(path), {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!response.ok || !response.body) {
    await json(response); // reuse the detail-extracting error path
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload) as E);
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  }
}

// Generate the blueprint over SSE, invoking `onEvent` per step (model, prompt,
// streamed output, saved result).
export const generateBlueprintStream = (
  themeId: string,
  onEvent: (event: BlueprintEvent) => void,
  signal?: AbortSignal,
): Promise<void> =>
  postEventStream(`/themes/${themeId}/blueprint/stream`, onEvent, signal);

// Iteratively refine the latest blueprint over SSE (2-3 DEEP rounds).
export const refineBlueprintStream = (
  themeId: string,
  onEvent: (event: BlueprintEvent) => void,
  signal?: AbortSignal,
): Promise<void> =>
  postEventStream(
    `/themes/${themeId}/blueprint/refine/stream`,
    onEvent,
    signal,
  );

// RESEARCH discovery pass over SSE — broadens constituents and attributes Sources.
export const discoverBlueprintStream = (
  themeId: string,
  onEvent: (event: BlueprintEvent) => void,
  signal?: AbortSignal,
): Promise<void> =>
  postEventStream(
    `/themes/${themeId}/blueprint/discover/stream`,
    onEvent,
    signal,
  );

export async function approveBlueprint(themeId: string): Promise<Theme> {
  return json(
    await fetch(url(`/themes/${themeId}/blueprint/approve`), {
      method: "POST",
    }),
  );
}

// --- Tickets ---

export interface Ticket {
  id: string;
  theme_id: string;
  target: string;
  metric: string;
  reason: string | null;
  status: string;
  reason_code: string | null;
  current_estimate: Record<string, unknown> | null;
  // A Deep Research answer awaiting admin review (value + cited source URL), or null.
  research_proposal: ResearchProposal | null;
  created_at: string;
  updated_at: string;
}

// What Deep Research found for a ticket, persisted for the admin to accept or reject.
export interface ResearchProposal {
  value?: string | number | null;
  unit?: string | null;
  as_of_date?: string | null;
  confidence?: string | null;
  source_url?: string | null;
  source_publisher?: string | null;
  notes?: string | null;
  by?: string | null;
}

// A single progress event from the ticket Deep Research stream. The whole batch is one
// run. `event` names the step (model / endpoint / batch_start / prompt / llm_start /
// thought / research / chunk / parse / proposed / auto_resolved / skipped / error / done);
// other fields depend on the step (see engine tickets/research.py). The per-ticket result
// events (proposed / auto_resolved / skipped) carry `ticket_id`; batch_start lists them all.
export interface TicketResearchEvent {
  event: string;
  ticket_id?: string;
  [key: string]: unknown;
}

export interface GenerateResult {
  created: number;
  skipped: number;
}

export async function listTickets(
  themeId: string,
  status?: string,
): Promise<Ticket[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return json(
    await fetch(url(`/themes/${themeId}/tickets${query}`), {
      cache: "no-store",
    }),
  );
}

export async function generateTickets(
  themeId: string,
): Promise<GenerateResult> {
  return json(
    await fetch(url(`/themes/${themeId}/tickets/generate`), { method: "POST" }),
  );
}

export async function listTicketSources(ticketId: string): Promise<Source[]> {
  return json(
    await fetch(url(`/tickets/${ticketId}/sources`), { cache: "no-store" }),
  );
}

export interface TicketEvent {
  id: string;
  ticket_id: string;
  from_status: string | null;
  to_status: string;
  actor: string;
  reason_code: string | null;
  created_at: string;
}

export async function listTicketEvents(
  ticketId: string,
): Promise<TicketEvent[]> {
  return json(
    await fetch(url(`/tickets/${ticketId}/events`), { cache: "no-store" }),
  );
}

export async function resolveTicket(
  ticketId: string,
  status: "UNRESOLVABLE" | "DEFERRED",
  reasonCode: string,
): Promise<Ticket> {
  return json(
    await fetch(url(`/tickets/${ticketId}/resolve`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, reason_code: reasonCode }),
    }),
  );
}

// Resolve the selected tickets with the Deep Research agent over SSE (run sequentially).
// Each ticket either gets a reviewable proposal (status stays OPEN) or auto-resolves.
export const researchTicketsStream = (
  themeId: string,
  ticketIds: string[],
  onEvent: (event: TicketResearchEvent) => void,
  signal?: AbortSignal,
): Promise<void> =>
  postEventStream<TicketResearchEvent>(
    `/themes/${themeId}/tickets/research/stream`,
    onEvent,
    signal,
    { ticket_ids: ticketIds },
  );

// Reject a Deep Research proposal — clears it, leaving the ticket's status unchanged.
export async function dismissTicketProposal(ticketId: string): Promise<Ticket> {
  return json(
    await fetch(url(`/tickets/${ticketId}/research/dismiss`), {
      method: "POST",
    }),
  );
}

export async function uploadTicketEvidence(
  ticketId: string,
  opts: {
    file?: File;
    url?: string;
    type?: string;
    publisher?: string;
    as_of_date?: string;
    language?: string;
  },
): Promise<Source> {
  const form = new FormData();
  if (opts.file) form.append("file", opts.file);
  if (opts.url) form.append("url", opts.url);
  form.append("type", opts.type ?? "report");
  if (opts.publisher) form.append("publisher", opts.publisher);
  if (opts.as_of_date) form.append("as_of_date", opts.as_of_date);
  if (opts.language) form.append("language", opts.language);
  return json(
    await fetch(url(`/tickets/${ticketId}/evidence`), {
      method: "POST",
      body: form,
    }),
  );
}

// Read-only data-quality meter for a theme's currently published graph.
// Returns null when nothing has been published yet (404).
export async function getThemeQuality(
  id: string,
): Promise<QualityReport | null> {
  const response = await fetch(url(`/themes/${id}/quality`), {
    cache: "no-store",
  });
  if (response.status === 404) return null;
  return json(response);
}

// --- Publish (M4-PUB-04) ---

export interface GateViolation {
  edge: string;
  field: string;
  detail: string;
}

export interface GateReport {
  theme_id: string;
  version: number;
  checked_edges: number;
  violations: GateViolation[];
  clean: boolean;
  passed: boolean;
}

export interface CompletenessReport {
  publishable_edges: number;
  gap_edges: number;
  total_edges: number;
  completeness: number;
  threshold: number;
  meets_threshold: boolean;
}

export interface PublishPreview {
  theme_id: string;
  build_version: number;
  completeness: CompletenessReport;
  gate: GateReport;
  can_publish: boolean;
}

export interface PublishResult {
  theme_id: string;
  snapshot_version: number;
  source_build_version: number;
  completeness: number;
  published_by: string;
  published_at: string;
  edges: number;
  ghost_edges: number;
  overridden: boolean;
}

// Assemble + gate the latest Staging build WITHOUT publishing — shows completeness and
// any blocking validation violations. Returns null when there is no build yet (409).
export async function getPublishPreview(
  themeId: string,
): Promise<PublishPreview | null> {
  const response = await fetch(url(`/themes/${themeId}/publish/preview`), {
    cache: "no-store",
  });
  if (response.status === 409) return null;
  return json(response);
}

// Publish the latest build to Production (explicit human action). Supply
// `overrideReason` to publish past validation issues (logged server-side).
export async function publishTheme(
  themeId: string,
  actor: string,
  overrideReason?: string,
): Promise<PublishResult> {
  return json(
    await fetch(url(`/themes/${themeId}/publish`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor,
        override_reason: overrideReason?.trim() || null,
      }),
    }),
  );
}

// --- CVE run (M3-ORCH-08) ---

export interface CveRunSummary {
  run_id: string | null;
  status: string;
  build_version: number;
  documents_ingested: number;
  claims: number;
  edges: number;
  publishable_edges: number;
  ghost_edges: number;
  estimated_edges: number;
}

// Run the CVE pipeline over the theme's sources + tickets and persist a Staging build
// (the artifact Publish consumes). Can take a while (LLM extraction per document).
export async function runThemeCve(themeId: string): Promise<CveRunSummary> {
  return json(
    await fetch(url(`/themes/${themeId}/cve/run`), { method: "POST" }),
  );
}

// --- Jobs (M7-SCHED-04) ---

export interface CveJob {
  id: string;
  theme_id: string;
  company: string;
  trigger: string;
  reason: string | null;
  affected_edges: string[];
  status: string;
  attempts: number;
  next_retry_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function listJobs(
  themeId?: string,
  status?: string,
): Promise<CveJob[]> {
  const params = new URLSearchParams();
  if (themeId) params.set("theme_id", themeId);
  if (status) params.set("status", status);
  const qs = params.toString();
  return json(
    await fetch(url(`/jobs${qs ? `?${qs}` : ""}`), { cache: "no-store" }),
  );
}
