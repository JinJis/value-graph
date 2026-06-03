// [M5-ENCODE-04] The signature feature: encode data quality VISUALLY, never hide it.
// Confidence -> edge style (solid/dashed/ghost); freshness -> a green/amber/red dot;
// gaps -> drawn ghost "?" edges. Pure mapping here; the canvas + legend consume it.
// (PRD §6.4/§9.)

export type Confidence = "verified" | "derived" | "estimated";
export type Freshness = "fresh" | "aging" | "stale" | "gap";

export interface ConfidenceStyle {
  label: string;
  style: "solid" | "dashed" | "ghost";
  colorHex: string;
  rgb: [number, number, number]; // 0..1, for per-instance/point colour buffers
  radiusScale: number; // verified thick -> estimated thin (reinforces the hierarchy)
  particleOpacity: number;
}

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

// verified = solid bright · derived = dashed mid · estimated = ghost faint.
const CONFIDENCE: Record<Confidence, ConfidenceStyle> = {
  verified: {
    label: "Verified",
    style: "solid",
    colorHex: "#6ee7a8",
    rgb: hexToRgb("#6ee7a8"),
    radiusScale: 1.0,
    particleOpacity: 0.95,
  },
  derived: {
    label: "Derived",
    style: "dashed",
    colorHex: "#5ea0ff",
    rgb: hexToRgb("#5ea0ff"),
    radiusScale: 0.72,
    particleOpacity: 0.7,
  },
  estimated: {
    label: "Estimated",
    style: "ghost",
    colorHex: "#7c8aa6",
    rgb: hexToRgb("#7c8aa6"),
    radiusScale: 0.45,
    particleOpacity: 0.4,
  },
};

export function confidenceStyle(confidence: string): ConfidenceStyle {
  return CONFIDENCE[
    (confidence as Confidence) in CONFIDENCE
      ? (confidence as Confidence)
      : "estimated"
  ];
}

// Freshness dot: green (fresh) · amber (aging) · red (stale) · grey (gap/unknown).
const FRESHNESS: Record<Freshness, string> = {
  fresh: "#36d399",
  aging: "#fbbd23",
  stale: "#f87272",
  gap: "#9aa4b2",
};

export function freshnessColor(freshness: string): string {
  return FRESHNESS[
    (freshness as Freshness) in FRESHNESS ? (freshness as Freshness) : "gap"
  ];
}

// Drawn (never omitted) gap edges: a faint dashed "?" connection.
export const GHOST_COLOR = "#5b6478";

export interface LegendEntry {
  label: string;
  hint: string;
  colorHex: string;
}

export const CONFIDENCE_LEGEND: LegendEntry[] = [
  { label: "Verified", hint: "solid", colorHex: CONFIDENCE.verified.colorHex },
  { label: "Derived", hint: "dashed", colorHex: CONFIDENCE.derived.colorHex },
  {
    label: "Estimated",
    hint: "ghost",
    colorHex: CONFIDENCE.estimated.colorHex,
  },
  { label: "Gap", hint: 'ghost "?"', colorHex: GHOST_COLOR },
];

export const FRESHNESS_LEGEND: LegendEntry[] = [
  { label: "Fresh", hint: "< 30d", colorHex: FRESHNESS.fresh },
  { label: "Aging", hint: "older", colorHex: FRESHNESS.aging },
  { label: "Stale", hint: "update due", colorHex: FRESHNESS.stale },
  { label: "Gap", hint: "unknown", colorHex: FRESHNESS.gap },
];
