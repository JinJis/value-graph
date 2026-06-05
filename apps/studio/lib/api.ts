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
// manually. Shared by the blueprint generate / refine / discover progress streams.
async function postEventStream(
  path: string,
  onEvent: (event: BlueprintEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(url(path), {
    method: "POST",
    headers: { Accept: "text/event-stream" },
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
          onEvent(JSON.parse(payload) as BlueprintEvent);
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
  created_at: string;
  updated_at: string;
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
