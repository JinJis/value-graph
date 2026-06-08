"use client";

import { useEffect, useRef, useState } from "react";

import {
  findQuoteRange,
  highlightStrategy,
  type SourceRef,
  sourceContentUrl,
  textFragmentUrl,
} from "./highlight";
import { PdfHighlight } from "./PdfHighlight";

/**
 * Shared source-highlight viewer (Studio + Terminal). Given a verbatim `quote` and its
 * `source`, it proves provenance by either:
 *  - stored text/HTML  -> fetch the doc, render it as safe escaped text with the quote
 *    wrapped in a yellow <mark>, scrolled into view;
 *  - stored PDF        -> render with pdf.js and paint a yellow highlight on the exact
 *    text-layer spans of the quote, jumping to the page (see PdfHighlight);
 *  - external URL only -> a "open original at the highlight" deep link (#:~:text=) plus the
 *    verbatim quote (we never embed third-party full text — CLAUDE.md §6).
 */
export interface SourceHighlightProps {
  source: SourceRef;
  quote: string;
  /** Pass false (e.g. a compliance toggle) to force deep-link even for stored docs. */
  allowEmbed?: boolean;
}

const MARK_STYLE: React.CSSProperties = {
  background: "#fde047",
  color: "#0f172a",
  padding: "0 1px",
  borderRadius: 2,
};

const QUOTE_STYLE: React.CSSProperties = {
  borderLeft: "3px solid #fde047",
  background: "#fffbea",
  padding: "6px 10px",
  margin: "8px 0",
  fontStyle: "italic",
  color: "#334155",
  fontSize: 13,
};

function ResearchedQuote({ quote }: { quote: string }) {
  return <div style={QUOTE_STYLE}>“{quote}”</div>;
}

// Stored text/HTML: fetch + render as ESCAPED text (XSS-safe), highlighting the quote.
function TextHighlight({
  source,
  quote,
}: {
  source: SourceRef;
  quote: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const markRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let alive = true;
    setText(null);
    setError(null);
    fetch(sourceContentUrl(source.source_id))
      .then((r) =>
        r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`)),
      )
      .then((t) => alive && setText(t))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [source.source_id]);

  useEffect(() => {
    if (markRef.current)
      markRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [text]);

  if (error)
    return (
      <>
        <ResearchedQuote quote={quote} />
        <p style={{ color: "#b91c1c", fontSize: 13 }}>
          Couldn’t load the document ({error}).
        </p>
      </>
    );
  if (text === null)
    return <p style={{ fontSize: 13, color: "#64748b" }}>Loading document…</p>;

  const range = findQuoteRange(text, quote);
  const body = !range ? (
    <>
      <p style={{ fontSize: 12, color: "#b45309" }}>
        Couldn’t locate the exact quote in the document — showing it in full.
      </p>
      {text}
    </>
  ) : (
    <>
      {text.slice(0, range.start)}
      <mark ref={markRef} style={MARK_STYLE}>
        {text.slice(range.start, range.end)}
      </mark>
      {text.slice(range.end)}
    </>
  );

  return (
    <pre
      style={{
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        fontSize: 12,
        lineHeight: 1.5,
        maxHeight: 360,
        overflow: "auto",
        background: "#ffffff",
        border: "1px solid #e2e8f0",
        borderRadius: 6,
        padding: 12,
        margin: 0,
        fontFamily: "ui-monospace, monospace",
      }}
    >
      {body}
    </pre>
  );
}

// External URL-only citation: deep-link to the original at the highlighted text.
function DeepLink({ source, quote }: { source: SourceRef; quote: string }) {
  const href = source.url ? textFragmentUrl(source.url, quote) : null;
  return (
    <>
      <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 4px" }}>
        Reported by research from this source — open it to verify the highlight:
      </p>
      <ResearchedQuote quote={quote} />
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: 13 }}
        >
          ↗ Open original at the highlighted text
        </a>
      ) : (
        <p style={{ fontSize: 12, color: "#b45309" }}>
          No source URL on file for this citation.
        </p>
      )}
    </>
  );
}

export function SourceHighlight({
  source,
  quote,
  allowEmbed = true,
}: SourceHighlightProps) {
  const strategy = highlightStrategy(source, { allowEmbed });
  if (strategy === "pdf") return <PdfHighlight source={source} quote={quote} />;
  if (strategy === "html" || strategy === "text")
    return <TextHighlight source={source} quote={quote} />;
  return <DeepLink source={source} quote={quote} />;
}
