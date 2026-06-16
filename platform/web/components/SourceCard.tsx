"use client";

// Live Context source previews — wireframe "화면 상세" Live panel. Instead of a title
// list, each cited source renders in its NATIVE form with the cited passage highlighted:
//   filing → a mini document page (page badge + amber-highlighted line)
//   web/news → browser chrome (URL bar) + headline + highlighted phrase
//   data/metric → an extracted-data card with the computation
// Clicking a preview opens the full SourceViewer. "정말 거기 그렇게 써 있다"를 눈으로 확인 = 신뢰.
// We only ever show the extracted snippet + a link to the real document (no full-text
// redistribution), and surrounding text is drawn as skeleton lines.

import { FreshnessDot, FRESH_LABEL, TrustLegend } from "./ui";

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
  snippet?: string;
  ticker?: string;
  page?: string;
  table?: string[][];   // extracted figures (header row first, cited row = first data row)
  used?: boolean;       // evidence flag (set from the answer's [n] / artifact backing)
};

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

export function SourceCard({ c, onExpand }: { c: Citation; onExpand?: (c: Citation) => void }) {
  const shape = sourceShape(c);
  const fresh = c.freshness ? FRESH_LABEL[c.freshness] || c.freshness : null;
  const open = c.url ? (
    <a className="sp-open" href={c.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
      {OPEN_LABEL[shape]}
    </a>
  ) : null;
  const foot = (
    <div className="sp-foot mono">
      <FreshnessDot f={c.freshness} />
      <span>{shape === "web" ? "맥락정보" : c.as_of ? `as_of ${c.as_of}` : (fresh ?? "출처")}</span>
      {open}
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
            <span className="sp-title">{c.source || "공시 문서"}</span>
            {c.page ? <span className="sp-page mono">{c.page}</span> : null}
          </div>
          <div className="sp-doc">
            {c.doc_type && c.doc_type !== "news" ? <div className="sp-doc-sec mono">{c.doc_type}</div> : null}
            <span className="sp-skel" style={{ width: "82%" }} />
            {c.snippet ? <div className="sp-quote">{c.snippet}</div> : <span className="sp-skel" style={{ width: "95%" }} />}
            <span className="sp-skel" style={{ width: "94%" }} />
            <span className="sp-skel" style={{ width: "60%" }} />
          </div>
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
            <span className="sp-title">{c.source || "추출 데이터"}</span>
            {c.ticker ? <span className="sp-page mono">{c.ticker}</span> : null}
          </div>
          {c.table ? <SrcTable table={c.table} /> : null}
          {c.snippet ? <div className="sp-data mono">{c.snippet}</div>
            : (!c.table ? <div className="sp-data mono">계산에 사용된 값</div> : null)}
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
