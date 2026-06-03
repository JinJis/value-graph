// [M7-NEXT-02] Theme-level "upcoming updates" timeline, aggregated from each edge's
// next_expected_update (driven by the disclosure calendar, M7-CAL-01). Items whose
// expected date has passed are flagged stale — the data is overdue for a refresh.

import type { PublishedGraph } from "../canvas/types";

export interface TimelineEntry {
  key: string;
  label: string; // "SUPPLIER → CUSTOMER"
  nextUpdate: string; // ISO date
  daysUntil: number; // negative => overdue
  stale: boolean;
}

export interface Timeline {
  entries: TimelineEntry[]; // soonest (incl. overdue) first
  overdue: number;
}

const MS_PER_DAY = 86_400_000;

export function buildTimeline(
  graph: PublishedGraph,
  today: Date = new Date(),
): Timeline {
  const start = today.getTime();
  const entries: TimelineEntry[] = [];
  for (const e of graph.edges) {
    const next = e.next_expected_update;
    if (!next) continue;
    const when = Date.parse(next);
    if (Number.isNaN(when)) continue;
    const daysUntil = Math.floor((when - start) / MS_PER_DAY);
    entries.push({
      key: `${e.supplier}->${e.customer}`,
      label: `${e.supplier} → ${e.customer}`,
      nextUpdate: next,
      daysUntil,
      // Past the expected date, or the figure was already scored stale.
      stale: daysUntil < 0 || e.freshness === "stale",
    });
  }
  entries.sort((a, b) => a.nextUpdate.localeCompare(b.nextUpdate));
  return { entries, overdue: entries.filter((x) => x.stale).length };
}

export function untilLabel(daysUntil: number): string {
  if (daysUntil < 0) return `${-daysUntil}d overdue`;
  if (daysUntil === 0) return "today";
  if (daysUntil === 1) return "in 1 day";
  return `in ${daysUntil} days`;
}
