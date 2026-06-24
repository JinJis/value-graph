"use client";

// Live Context source previews — wireframe "화면 상세" Live panel. Instead of a title
// list, each cited source renders in its NATIVE form with the cited passage highlighted:
//   filing → a mini document page (page badge + amber-highlighted line)
//   web/news → browser chrome (URL bar) + headline + highlighted phrase
//   data/metric → an extracted-data card with the computation
// Clicking a preview opens the full SourceViewer. "정말 거기 그렇게 써 있다"를 눈으로 확인 = 신뢰.
// We only ever show the extracted snippet + a link to the real document (no full-text
// redistribution), and surrounding text is drawn as skeleton lines.

import { useState } from "react";
import { CadenceTag, FreshnessDot, FRESH_LABEL, TrustLegend } from "./ui";

export { FreshnessDot, TrustLegend };

export type Citation = {
  tool?: string;
  source?: string;
  url?: string;
  index?: number;
  kind?: string; // filing | news | metric | data
  doc_type?: string;
  as_of?: string;
  freshness?: string; // fresh | aging | stale | gap
  cadence?: string;   // intraday|daily|event|scheduled|streaming|one_shot — periodic ⇒ alertable
  category?: string;  // market|fundamentals|valuation|filings|gurus|macro|news|…
  snippet?: string;
  ticker?: string;
  page?: string;
  table?: string[][];   // extracted figures (header row first, cited row = first data row)
  used?: boolean;       // evidence flag (set from the answer's [n] / artifact backing)
  evidence_image_url?: string;  // PH-PROV2: /evidence?… → highlighted screenshot of the filing line
  confidence?: string;  // PH-THINK verify pass: high | medium | low (evidentiary support)
  confidence_why?: string;
};

// PH-THINK: a small confidence chip (how well this source supports the question).
const CONF: Record<string, { label: string; cls: string }> = {
  high: { label: "신뢰 높음", cls: "high" },
  medium: { label: "신뢰 보통", cls: "med" },
  low: { label: "신뢰 낮음", cls: "low" },
};
export function ConfBadge({ c }: { c: Citation }) {
  const k = (c.confidence || "").toLowerCase();
  const m = CONF[k];
  if (!m) return null;
  return <span className={`sp-conf ${m.cls}`} title={c.confidence_why || "근거의 질문 적합도"}>{m.label}</span>;
}

// PH-PROV2: map the agent's gateway-relative /evidence URL to the web BFF route the
// browser can fetch (carries the session → tenant key).
export function evidenceSrc(url?: string): string | null {
  return url ? url.replace(/^\/evidence/, "/api/evidence") : null;
}

// PH-PROV3: the real source-filing PDF for "원문 열기", derived from the same /evidence
// params (market + accession). Null if the citation carries no evidence link.
export function evidenceDocSrc(url?: string): string | null {
  const q = url?.split("?")[1];
  if (!q) return null;
  const p = new URLSearchParams(q);
  const market = p.get("market"), accession = p.get("accession");
  if (!market || !accession) return null;
  return `/api/evidence/doc?market=${encodeURIComponent(market)}&accession=${encodeURIComponent(accession)}`;
}

// PH-PROV2: inline teaser of the highlighted-filing screenshot, shown right on the
// card so the evidence is visible without expanding. Lazy-loaded; on 204/error it
// removes itself (never a broken image). Click the card to open the full viewer.
function InlineEvidence({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <figure className="sp-evidence">
      <img className="sp-evidence-img" src={src} loading="lazy"
           alt="원문에서 인용한 수치 하이라이트" onError={() => setFailed(true)} />
      <figcaption className="sp-evidence-cap mono">📷 실제 공시 원문 · 노란 박스 = 인용 수치 · 클릭해 확대</figcaption>
    </figure>
  );
}

// A compact extracted-data table for the preview — header row + data rows, the
// cited (latest) row highlighted. Shows the *real* figures the answer used.
export function SrcTable({ table }: { table: string[][] }) {
  if (!table?.length) return null;
  const [head, ...rows] = table;
  return (
    <table className="sp-table mono">
      <thead><tr>{head.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, ri) => (
          <tr key={ri} className={ri === 0 ? "cited" : ""}>{r.map((cell, ci) => <td key={ci}>{cell}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

// filing · web · data — the three native preview shapes.
export function sourceShape(c: Citation): "filing" | "web" | "data" {
  if (c.kind === "filing") return "filing";
  if (c.kind === "news") return "web";
  if (c.kind === "metric" || c.kind === "data") return "data";
  if (c.url && /^https?:\/\//.test(c.url)) return "web";
  return "data";
}

export function hostOf(url?: string): string {
  if (!url) return "";
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return url.replace(/^https?:\/\//, "").split("/")[0]; }
}

const OPEN_LABEL: Record<string, string> = { filing: "원문 ↗", web: "기사 ↗", data: "표 ↗" };

export function SourceCard({ c, onExpand, onPin, hideTitle }: { c: Citation; onExpand?: (c: Citation) => void; onPin?: (c: Citation) => void; hideTitle?: boolean }) {
  const [pinned, setPinned] = useState(false);
  const shape = sourceShape(c);
  const fresh = c.freshness ? FRESH_LABEL[c.freshness] || c.freshness : null;
  const evSrc = evidenceSrc(c.evidence_image_url);  // PH-PROV2: highlighted screenshot, if any
  const evBadge = evSrc ? <span className="sp-ev-badge mono" title="실제 공시 원문 스크린샷">📷 원문</span> : null;
  const open = c.url ? (
    <a className="sp-open" href={c.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
      {OPEN_LABEL[shape]}
    </a>
  ) : null;
  const foot = (
    <div className="sp-foot mono">
      <FreshnessDot f={c.freshness} />
      <span>{shape === "web" ? "맥락정보" : c.as_of ? `as_of ${c.as_of}` : (fresh ?? "출처")}</span>
      <CadenceTag c={c.cadence} />
      <ConfBadge c={c} />
      {open}
      {onPin && (
        <button type="button" className="sp-add" disabled={pinned} title="대시보드에 추가"
          onClick={(e) => { e.stopPropagation(); onPin(c); setPinned(true); }}>{pinned ? "✓ 대시보드" : "＋ 대시보드"}</button>
      )}
    </div>
  );

  return (
    <div className={`srcprev ${shape}`} role={onExpand ? "button" : undefined}
      onClick={onExpand ? () => onExpand(c) : undefined} title={onExpand ? "클릭하면 원문 전체로 펼쳐집니다" : undefined}>
      {shape === "filing" && (
        <>
          <div className="sp-head">
            {c.index ? <span className="sp-n mono">[{c.index}]</span> : null}
            <span className="sp-ic" aria-hidden>📄</span>
            {!hideTitle && <span className="sp-title">{c.source || "공시 문서"}</span>}
            {c.page ? <span className="sp-page mono">{c.page}</span> : null}
            {evBadge}
          </div>
          {evSrc ? <InlineEvidence src={evSrc} /> : (
            <div className="sp-doc">
              {c.doc_type && c.doc_type !== "news" ? <div className="sp-doc-sec mono">{c.doc_type}</div> : null}
              <span className="sp-skel" style={{ width: "82%" }} />
              {c.snippet ? <div className="sp-quote">{c.snippet}</div> : <span className="sp-skel" style={{ width: "95%" }} />}
              <span className="sp-skel" style={{ width: "94%" }} />
              <span className="sp-skel" style={{ width: "60%" }} />
            </div>
          )}
          {foot}
        </>
      )}

      {shape === "web" && (
        <>
          <div className="sp-chrome">
            <span className="sp-dots" aria-hidden><i /><i /><i /></span>
            <span className="sp-url mono">🔒 {hostOf(c.url) || c.source || "web"}…</span>
          </div>
          <div className="sp-web">
            <div className="sp-headline">{c.source || hostOf(c.url) || "기사"}</div>
            {c.as_of ? <div className="sp-wmeta mono">{c.as_of}</div> : null}
            {c.snippet ? <div className="sp-wtext">“<mark>{c.snippet}</mark>”</div> : null}
          </div>
          {foot}
        </>
      )}

      {shape === "data" && (
        <>
          <div className="sp-head">
            {c.index ? <span className="sp-n mono">[{c.index}]</span> : null}
            <span className="sp-ic" aria-hidden>▤</span>
            {!hideTitle && <span className="sp-title">{c.source || "추출 데이터"}</span>}
            {c.ticker ? <span className="sp-page mono">{c.ticker}</span> : null}
            {evBadge}
          </div>
          {c.table ? <SrcTable table={c.table} /> : null}
          {c.snippet ? <div className="sp-data mono">{c.snippet}</div>
            : (!c.table ? <div className="sp-data mono">계산에 사용된 값</div> : null)}
          {evSrc ? <InlineEvidence src={evSrc} /> : null}
          {foot}
        </>
      )}
    </div>
  );
}

// Compact inline chip used under a message ([n] + source + freshness dot).
const KIND_ICON: Record<string, string> = { filing: "📄", news: "📰", metric: "📊", data: "📎" };
export function CiteChip({ c }: { c: Citation }) {
  const icon = (c.kind && KIND_ICON[c.kind]) || "📎";
  const body = (
    <>
      {c.index ? <span className="cnum">[{c.index}]</span> : null}
      <span aria-hidden>{icon}</span> {c.source || "출처"}
      <FreshnessDot f={c.freshness} />
    </>
  );
  return c.url ? (
    <a className="cite-chip" href={c.url} target="_blank" rel="noreferrer" title={c.snippet || c.url}>{body}</a>
  ) : (
    <span className="cite-chip" title={c.snippet || ""}>{body}</span>
  );
}
