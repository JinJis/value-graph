// [M6-FEED-04] Read-only client for the Live Context Feed (Production-adjacent).

import { engineUrl } from "../canvas/api";
import type { FeedItem } from "./types";

export async function getFeed(
  themeId: string,
  entity?: string,
): Promise<FeedItem[]> {
  const qs = entity ? `?entity=${encodeURIComponent(entity)}` : "";
  const res = await fetch(`${engineUrl()}/themes/${themeId}/feed${qs}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
