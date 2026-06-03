// [M6-PROV-02] Per-figure provenance: value + interval, confidence, "as of … · N days
// old · next: …", and the Source link(s). Radical honesty about uncertainty — every
// exposed figure shows where it came from and how stale it is.

import type { ConfidenceInterval, SourceRef } from "../canvas/types";

export interface FigureProvenance {
  value: number | null;
  unit: string; // e.g. "% of cost"
  interval: ConfidenceInterval | null;
  confidence: string;
  freshness: string;
  asOf: string | null;
  nextUpdate: string | null;
  sources: SourceRef[];
}

const MS_PER_DAY = 86_400_000;

export function daysOld(
  asOf: string | null,
  today: Date = new Date(),
): number | null {
  if (!asOf) return null;
  const then = Date.parse(asOf);
  if (Number.isNaN(then)) return null;
  return Math.max(0, Math.floor((today.getTime() - then) / MS_PER_DAY));
}

export function formatValue(value: number | null, unit: string): string {
  return value != null ? `${value.toFixed(1)}${unit ? ` ${unit}` : ""}` : "—";
}

export function formatInterval(interval: ConfidenceInterval | null): string {
  if (!interval) return "";
  return `[${interval.low.toFixed(1)} – ${interval.high.toFixed(1)}]`;
}

// Stale = scored stale, or the next expected update has already passed (overdue).
export function isStale(
  freshness: string,
  nextUpdate: string | null,
  today: Date = new Date(),
): boolean {
  if (freshness === "stale") return true;
  if (!nextUpdate) return false;
  const next = Date.parse(nextUpdate);
  return !Number.isNaN(next) && next < today.getTime();
}

// "as of 2026-05-20 · 13 days old · next: 2026-08-15"
export function formatFreshnessLine(
  asOf: string | null,
  nextUpdate: string | null,
  today: Date = new Date(),
): string {
  const parts: string[] = [];
  parts.push(asOf ? `as of ${asOf}` : "as of —");
  const age = daysOld(asOf, today);
  if (age != null) parts.push(`${age} days old`);
  parts.push(nextUpdate ? `next: ${nextUpdate}` : "next: —");
  return parts.join(" · ");
}
