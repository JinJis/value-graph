// [M5-CANVAS-01] Read-only client for the Engine's Production endpoints.
// Terminal reads Production ONLY (CLAUDE.md Two-Track invariant).

import type { PublishedGraph, ThemeSummary } from "./types";

// Calls go to this app's OWN origin under "/engine", which Next.js rewrites server-side
// to the engine (see next.config.mjs) — works behind any tunnel/proxy with no CORS.
export function engineUrl(): string {
  return process.env.NEXT_PUBLIC_ENGINE_URL ?? "/engine";
}

const url = (path: string): string => `${engineUrl()}${path}`;

export async function listThemes(): Promise<ThemeSummary[]> {
  const res = await fetch(url("/themes"), { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// Returns null when the theme has no published graph yet (404).
export async function getPublishedGraph(
  themeId: string,
): Promise<PublishedGraph | null> {
  const res = await fetch(url(`/themes/${themeId}/graph`), {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
