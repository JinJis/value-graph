/**
 * Source-highlight primitives, shared by Studio and Terminal.
 *
 * A figure's provenance is a verbatim `quote` plus a `SourceRef`. To "prove" the figure we
 * show the source document and highlight that exact span. These pure helpers decide HOW
 * (embed a stored doc vs. deep-link an external URL) and WHERE (locate the quote in text),
 * with no React/DOM dependency so they're trivially testable and reused by both apps.
 */

/** One backing source for an edge figure (mirrors the engine's enriched edge_sources ref). */
export interface SourceRef {
  source_id: string;
  url?: string | null;
  type?: string | null;
  content_type?: string | null;
  /** True when the engine holds the document bytes (admin upload) -> embeddable. */
  has_content?: boolean | null;
  as_of_date?: string | null;
}

export type HighlightStrategy = "pdf" | "html" | "text" | "link";

/**
 * Pick how to show a source. The HYBRID rule (CLAUDE.md §6): only documents we hold bytes
 * for (`has_content`) are embedded; everything else — external URL-only citations — is a
 * deep-link, so we never redistribute third-party full text.
 */
export function highlightStrategy(
  ref: Pick<SourceRef, "content_type" | "has_content">,
  { allowEmbed = true }: { allowEmbed?: boolean } = {},
): HighlightStrategy {
  if (!ref.has_content || !allowEmbed) return "link";
  const ct = (ref.content_type ?? "").toLowerCase();
  if (ct.includes("pdf")) return "pdf";
  if (ct.includes("html")) return "html";
  return "text";
}

/** The engine endpoint that serves a stored source's bytes (proxied at /engine in both apps). */
export function sourceContentUrl(sourceId: string): string {
  return `/engine/sources/${encodeURIComponent(sourceId)}/content`;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Locate `quote` inside `text`, returning [start, end) char offsets or null.
 * Tries an exact match first, then a whitespace-insensitive match (PDF/HTML text extraction
 * collapses or reflows whitespace). First match only — a quote that repeats verbatim may
 * land on the wrong occurrence (acceptable v1; precise locators are a later enhancement).
 */
export function findQuoteRange(
  text: string,
  quote: string,
): { start: number; end: number } | null {
  const q = quote.trim();
  if (!q || !text) return null;
  const direct = text.indexOf(q);
  if (direct !== -1) return { start: direct, end: direct + q.length };
  const pattern = escapeRegExp(q).replace(/\s+/g, "\\s+");
  const m = new RegExp(pattern, "i").exec(text);
  return m ? { start: m.index, end: m.index + m[0].length } : null;
}

/**
 * Build a Text-Fragment deep link (`#:~:text=…`) so the browser scrolls to and highlights
 * the quote on the original page. Long quotes use the `start,end` form (first/last few words)
 * to stay within practical URL limits.
 */
export function textFragmentUrl(url: string, quote: string): string {
  const q = quote.trim().replace(/\s+/g, " ");
  if (!q) return url;
  const enc = encodeURIComponent;
  let frag: string;
  if (q.length <= 300) {
    frag = enc(q);
  } else {
    const words = q.split(" ");
    frag = `${enc(words.slice(0, 6).join(" "))},${enc(words.slice(-6).join(" "))}`;
  }
  const directive = `:~:text=${frag}`;
  return url.includes("#") ? `${url}${directive}` : `${url}#${directive}`;
}
