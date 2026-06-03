// [M6-FEED-04] Read-only client for the Live Context Feed (Production-adjacent).

import type { FeedItem } from "./types";

const ENGINE_URL =
  process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8000";

export async function getFeed(
  themeId: string,
  entity?: string,
): Promise<FeedItem[]> {
  const qs = entity ? `?entity=${encodeURIComponent(entity)}` : "";
  const res = await fetch(`${ENGINE_URL}/themes/${themeId}/feed${qs}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
