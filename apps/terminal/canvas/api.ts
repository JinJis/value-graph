// [M5-CANVAS-01] Read-only client for the Engine's Production endpoints.
// Terminal reads Production ONLY (CLAUDE.md Two-Track invariant).

import type { PublishedGraph, ThemeSummary } from "./types";

// Resolve the engine URL at runtime from the host the browser loaded Terminal from
// (port 8000), so it works on localhost and a remote server without a rebuild.
export function engineUrl(): string {
  if (process.env.NEXT_PUBLIC_ENGINE_URL)
    return process.env.NEXT_PUBLIC_ENGINE_URL;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
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
