// Company identity helpers — logos + monogram fallback — so the canvas and drawer can show
// *who* each node is at a glance (not just a sized sphere). Logos are loaded from a public
// logo CDN at DISPLAY time and never stored/redistributed; a colored monogram (initials)
// always renders when no logo resolves, so the UI is never blank.
//
// NOTE (CLAUDE.md §6): displaying third-party brand logos is a trademark/brand-usage question
// to confirm with a professional before production. We only hot-link public logos for display
// and fall back to a neutral monogram — we do not cache or rehost them.

import type { GraphCompany } from "./types";

// Legal-form + generic descriptor words to strip before guessing a brand domain.
const NOISE =
  /\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|ag|sa|nv|llc|lp|group|holdings?|technologies|technology|industries|international|systems|semiconductors?|electronics|manufacturing|solutions|laboratories|labs)\b/gi;

const PALETTE = [
  "#6366f1",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
  "#f97316",
  "#3b82f6",
];

// A stable, friendly accent color for a company's monogram chip (hashed from the ticker).
export function monogramColor(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

// 1–2 letter initials: company-name initials when possible, else the ticker.
export function initials(name: string, ticker: string): string {
  const words = name
    .replace(/[^A-Za-z0-9 ]/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (ticker || "?").slice(0, 2).toUpperCase();
}

// Best-effort brand-domain guesses from a company name, e.g. "SK Hynix" -> ["sk.com",
// "skhynix.com"], "NVIDIA Corporation" -> ["nvidia.com"]. Multi-brand / localized names often
// miss — that's fine, the logo CDN 404s and we fall back to the monogram.
export function guessDomains(name: string): string[] {
  const cleaned = name
    .toLowerCase()
    .replace(/[.,&'’()/]/g, " ")
    .replace(NOISE, " ")
    .replace(/\s+/g, " ")
    .trim();
  const tokens = cleaned.split(" ").filter((t) => t.length >= 2);
  if (tokens.length === 0) return [];
  const out = [`${tokens[0]}.com`];
  if (tokens.length > 1) out.push(`${tokens.join("")}.com`); // e.g. skhynix.com
  return [...new Set(out)];
}

// Ordered logo URL candidates to try (first success wins). An explicit logo_url or domain on
// the company is preferred; otherwise we guess domains from the name.
export function logoCandidates(
  company: Pick<GraphCompany, "ticker" | "name" | "logo_url" | "domain">,
): string[] {
  if (company.logo_url) return [company.logo_url];
  const domains = company.domain
    ? [company.domain]
    : guessDomains(company.name);
  return domains.flatMap((d) => [
    `https://logo.clearbit.com/${d}`,
    `https://icons.duckduckgo.com/ip3/${d}.ico`,
  ]);
}
