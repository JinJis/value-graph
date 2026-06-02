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
