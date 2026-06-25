"use client";

// In-app filing viewer — renders the ORIGINAL disclosure (US SEC iXBRL · KR OpenDART) as the
// real document and highlights the exact cited element, then lets the user scroll/zoom the whole
// filing freely. The HTML is sanitized server-side (scripts stripped + strict CSP → no egress);
// we drop it into a sandboxed iframe (allow-same-origin, NO allow-scripts) so nothing in the
// filing runs, while the parent reaches into the same-origin document to highlight + scroll.
// No localStorage/sessionStorage. 204 → caller shows the external "원문 보기" link.

import { useEffect, useRef, useState } from "react";
import { Citation } from "./SourceCard";

type Target = { concept?: string; value?: string; text?: string };

// Map the agent's gateway-relative /evidence?… params → the HTML viewer route the browser fetches.
export function evidenceHtmlSrc(c: Citation): string | null {
  const q = c.evidence_image_url?.split("?")[1];
  if (!q) return null;
  const p = new URLSearchParams(q);
  const market = p.get("market"), accession = p.get("accession");
  if (!market || !accession) return null;
  const out = new URLSearchParams({ market, accession });
  const cik = p.get("cik");
  if (cik) out.set("cik", cik);
  return `/api/evidence/html?${out.toString()}`;
}

function targetOf(c: Citation): Target {
  const p = new URLSearchParams(c.evidence_image_url?.split("?")[1] || "");
  return {
    concept: p.get("concept") || undefined,
    value: p.get("value") || undefined,
    text: p.get("text") || c.snippet || undefined,
  };
}

// the value formatted with thousands commas at each plausible statement scale (ones/천/백만/억)
function valueCandidates(value: string): string[] {
  const v = Math.abs(parseFloat(value));
  if (!isFinite(v) || v === 0) return [];
  const out: string[] = [];
  for (const scale of [1, 1_000, 1_000_000, 100_000_000]) {
    const q = v / scale;
    if (q >= 1 && Math.abs(q - Math.round(q)) < 0.5) {
      const s = Math.round(q).toLocaleString("en-US");
      if (!out.includes(s)) out.push(s);
    }
  }
  return out;
}

const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

// Find the tightest element whose text contains `needle` (handles text split across <span>s,
// since the enclosing <p>/<td> still contains the whole phrase).
function findByText(doc: Document, needle: string): Element | null {
  const n = norm(needle);
  if (n.length < 6 || !doc.body) return null;
  let best: Element | null = null;
  doc.body.querySelectorAll("*").forEach((el) => {
    if (norm(el.textContent || "").includes(n)) {
      if (!best || (el.textContent || "").length < (best!.textContent || "").length) best = el;
    }
  });
  return best;
}

// Locate + highlight the cited element. Returns true if something was highlighted.
function highlight(doc: Document, t: Target): boolean {
  const style = doc.createElement("style");
  style.textContent =
    ".vg-hl{background:#fde68a !important;box-shadow:0 0 0 2px #f59e0b;border-radius:2px;scroll-margin-top:30vh;}";
  (doc.head || doc.body)?.appendChild(style);

  const mark = (el: Element | null): boolean => {
    if (!el) return false;
    el.classList.add("vg-hl");
    el.scrollIntoView({ block: "center" });
    return true;
  };

  // 1) US iXBRL — target the element tagged with the cited us-gaap concept (semantic, exact)
  if (t.concept) {
    const tags = t.concept.split(",").map((s) => s.split(":").pop()!.trim().toLowerCase()).filter(Boolean);
    const named = Array.from(doc.querySelectorAll("[name]"));
    const cands = t.value ? valueCandidates(t.value).map((s) => s.replace(/\s/g, "")) : [];
    for (const tag of tags) {
      const ms = named.filter((el) => (el.getAttribute("name") || "").split(":").pop()?.toLowerCase() === tag);
      if (!ms.length) continue;
      const byVal = cands.length
        ? ms.find((m) => cands.some((c) => (m.textContent || "").replace(/\s/g, "").includes(c)))
        : null;
      if (mark(byVal || ms[0])) return true;
    }
  }
  // 2) Text passage — find the leading slice of the cited snippet in the document body
  if (t.text) {
    const words = t.text.split(/\s+/).filter(Boolean);
    for (const n of [10, 8, 6, 4]) {
      const el = findByText(doc, words.slice(0, n).join(" "));
      if (el && mark(el)) return true;
    }
  }
  // 3) Value alone — the formatted number as a last resort
  if (t.value) {
    for (const cand of valueCandidates(t.value)) {
      const el = findByText(doc, cand);
      if (el && mark(el)) return true;
    }
  }
  return false;
}

export function FilingViewer({ c }: { c: Citation }) {
  const src = evidenceHtmlSrc(c);
  const [html, setHtml] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "none">(src ? "loading" : "none");
  const [hit, setHit] = useState<boolean | null>(null);
  const [zoom, setZoom] = useState(1);
  const frameRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (!src) return;
    let alive = true;
    (async () => {
      try {
        const r = await fetch(src);
        if (!alive) return;
        if (r.status !== 200) return setState("none");
        const text = await r.text();
        if (!alive) return;
        setHtml(text);
        setState("ready");
      } catch {
        if (alive) setState("none");
      }
    })();
    return () => { alive = false; };
  }, [src]);

  const onLoad = () => {
    const doc = frameRef.current?.contentDocument;
    if (!doc) return;
    try { setHit(highlight(doc, targetOf(c))); } catch { setHit(false); }
  };

  useEffect(() => {
    const doc = frameRef.current?.contentDocument;
    if (doc?.body) (doc.body.style as unknown as { zoom: string }).zoom = String(zoom);
  }, [zoom, html]);

  if (state === "none") {
    return (
      <div className="fv-empty">
        <div className="fv-empty-quote">{c.snippet ? `“${c.snippet}”` : "원문 미리보기를 불러올 수 없습니다."}</div>
        {c.url ? (
          <a className="fv-empty-link" href={c.url} target="_blank" rel="noreferrer">원문 보기 ↗</a>
        ) : null}
      </div>
    );
  }

  return (
    <div className="fv">
      <div className="fv-bar mono">
        <span className="fv-status">
          {state === "loading" ? "원문 불러오는 중…" : hit ? "📄 원문 · 인용 부분 하이라이트됨" : "📄 원문"}
        </span>
        <span className="fv-zoom">
          <button onClick={() => setZoom((z) => Math.max(0.6, +(z - 0.1).toFixed(2)))} aria-label="축소">－</button>
          <span>{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom((z) => Math.min(2, +(z + 0.1).toFixed(2)))} aria-label="확대">＋</button>
        </span>
        {c.url ? <a className="fv-orig" href={c.url} target="_blank" rel="noreferrer">원문 보기 ↗</a> : null}
      </div>
      {state === "loading" ? (
        <div className="fv-loading"><span className="fv-spinner" /> 원문 불러오는 중…</div>
      ) : (
        <iframe
          ref={frameRef}
          className="fv-frame"
          title="공시 원문"
          sandbox="allow-same-origin"
          srcDoc={html ?? ""}
          onLoad={onLoad}
        />
      )}
    </div>
  );
}
