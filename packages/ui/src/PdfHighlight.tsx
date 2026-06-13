"use client";

import { useEffect, useRef, useState } from "react";

import { findQuoteRange, type SourceRef, sourceContentUrl } from "./highlight";

/**
 * PDF source viewer with text-layer highlighting. Loads the stored PDF with pdf.js (lazily,
 * client-only), finds the first page whose text contains the verbatim `quote`, renders that
 * page to a canvas, lays pdf.js's transparent text layer over it, and paints a yellow
 * highlight on the spans that overlap the quote — proving the figure came from exactly there.
 *
 * pdf.js is ESM + worker-based, so it's imported only inside the effect (never at module load
 * / SSR). On any failure it falls back to embedding the browser PDF viewer + the quote.
 */

type Pdfjs = typeof import("pdfjs-dist");

let pdfjsPromise: Promise<Pdfjs> | null = null;

// Load pdf.js once and point it at the bundled worker (webpack emits it from this URL).
function loadPdfjs(): Promise<Pdfjs> {
  if (!pdfjsPromise) {
    pdfjsPromise = import("pdfjs-dist").then((pdfjs) => {
      const worker = new Worker(
        new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
        { type: "module" },
      );
      pdfjs.GlobalWorkerOptions.workerPort = worker;
      return pdfjs;
    });
  }
  return pdfjsPromise;
}

const HIGHLIGHT = "rgba(253, 224, 71, 0.45)"; // translucent yellow over the canvas text

// Paint the spans that overlap the quote; returns the first highlighted span (to scroll to).
function paintHighlight(
  textDivs: HTMLElement[],
  itemStrings: string[],
  quote: string,
): HTMLElement | null {
  // Concatenate item strings (space-joined, like the page search) tracking each item's range.
  let concat = "";
  const ranges: { start: number; end: number }[] = [];
  for (const s of itemStrings) {
    const start = concat.length;
    concat += s;
    ranges.push({ start, end: concat.length });
    concat += " ";
  }
  const match = findQuoteRange(concat, quote);
  let first: HTMLElement | null = null;
  for (let i = 0; i < textDivs.length; i++) {
    const div = textDivs[i];
    div.style.color = "transparent"; // canvas already shows the glyphs; keep selection layer hidden
    const r = ranges[i];
    if (match && r && r.start < match.end && r.end > match.start) {
      div.style.backgroundColor = HIGHLIGHT;
      div.style.borderRadius = "2px";
      if (!first) first = div;
    }
  }
  return first;
}

function Embed({ source, quote }: { source: SourceRef; quote: string }) {
  return (
    <>
      <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 4px" }}>
        Couldn’t render the highlight in-app — find this text in the document:
      </p>
      <div
        style={{
          borderLeft: "3px solid #fde047",
          background: "#fffbea",
          padding: "6px 10px",
          margin: "8px 0",
          fontStyle: "italic",
          color: "#334155",
          fontSize: 13,
        }}
      >
        “{quote}”
      </div>
      <iframe
        title="source document"
        src={sourceContentUrl(source.source_id)}
        style={{
          width: "100%",
          height: 480,
          border: "1px solid #e2e8f0",
          borderRadius: 6,
        }}
      />
    </>
  );
}

export function PdfHighlight({
  source,
  quote,
}: {
  source: SourceRef;
  quote: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<
    "loading" | "ready" | "notfound" | "error"
  >("loading");
  const [page, setPage] = useState<{ n: number; total: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const host = hostRef.current;
    if (!host) return;
    host.innerHTML = "";
    setState("loading");
    setPage(null);

    void (async () => {
      try {
        const pdfjs = await loadPdfjs();
        const doc = await pdfjs.getDocument({
          url: sourceContentUrl(source.source_id),
        }).promise;
        if (cancelled) return;

        // Find the first page whose text contains the quote.
        let target = 1;
        let found = false;
        for (let n = 1; n <= doc.numPages; n++) {
          const content = await doc.getPage(n).then((p) => p.getTextContent());
          if (cancelled) return;
          const text = content.items
            .map((it) => ("str" in it ? it.str : ""))
            .join(" ");
          if (findQuoteRange(text, quote)) {
            target = n;
            found = true;
            break;
          }
        }
        if (cancelled) return;
        setPage({ n: target, total: doc.numPages });
        setState(found ? "ready" : "notfound");

        // Render the target page + an overlaid text layer.
        const pdfPage = await doc.getPage(target);
        const scale = 1.4;
        const viewport = pdfPage.getViewport({ scale });
        const ratio = window.devicePixelRatio || 1;

        const wrapper = document.createElement("div");
        Object.assign(wrapper.style, {
          position: "relative",
          width: `${viewport.width}px`,
          height: `${viewport.height}px`,
          margin: "0 auto",
        });

        const canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("no 2d context");
        wrapper.appendChild(canvas);

        const textLayerDiv = document.createElement("div");
        Object.assign(textLayerDiv.style, {
          position: "absolute",
          inset: "0",
          width: `${viewport.width}px`,
          height: `${viewport.height}px`,
          lineHeight: "1",
        });
        // pdf.js v4 positions text spans via this CSS variable.
        textLayerDiv.style.setProperty("--scale-factor", String(scale));
        wrapper.appendChild(textLayerDiv);

        host.appendChild(wrapper);

        await pdfPage.render({
          canvasContext: ctx,
          viewport,
          transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
        }).promise;
        if (cancelled) return;

        const textLayer = new pdfjs.TextLayer({
          textContentSource: await pdfPage.getTextContent(),
          container: textLayerDiv,
          viewport,
        });
        await textLayer.render();
        if (cancelled) return;

        const first = paintHighlight(
          textLayer.textDivs,
          textLayer.textContentItemsStr,
          quote,
        );
        if (first)
          first.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch {
        if (!cancelled) setState("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [source.source_id, quote]);

  if (state === "error") return <Embed source={source} quote={quote} />;

  return (
    <div>
      <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 6px" }}>
        {state === "loading"
          ? "Rendering the source document…"
          : state === "notfound"
            ? "Couldn’t locate the exact quote — showing the document; the quote is:"
            : page
              ? `Highlighted on page ${page.n} of ${page.total}.`
              : ""}
      </p>
      {state === "notfound" && (
        <div
          style={{
            borderLeft: "3px solid #fde047",
            background: "#fffbea",
            padding: "6px 10px",
            margin: "8px 0",
            fontStyle: "italic",
            color: "#334155",
            fontSize: 13,
          }}
        >
          “{quote}”
        </div>
      )}
      <div
        ref={hostRef}
        style={{
          maxHeight: 520,
          overflow: "auto",
          background: "#f1f5f9",
          borderRadius: 6,
          padding: 8,
        }}
      />
    </div>
  );
}
