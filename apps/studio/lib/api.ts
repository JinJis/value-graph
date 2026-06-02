// Minimal client for the ValueGraph Engine API (CORS-enabled). Base URL from env.
const ENGINE_URL =
  process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8000";

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

const url = (path: string): string => `${ENGINE_URL}${path}`;

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
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
