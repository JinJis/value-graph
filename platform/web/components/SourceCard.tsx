"use client";

// Source-preview card — wireframe section C. Type-aware by `kind`: a filing shows a
// verbatim snippet, a metric its computation note, news ends in the context-not-forecast
// guardrail. Every card carries a freshness signal — the "trust by construction" brand.
// Trust primitives (FreshnessDot/TrustLegend) come from the design-system module.

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
};

const KIND_META: Record<string, { icon: string; label: string; open: string }> = {
  filing: { icon: "📄", label: "공시", open: "원문 열기 ↗" },
  news: { icon: "📰", label: "뉴스", open: "기사 열기 ↗" },
  metric: { icon: "📊", label: "지표", open: "원문 열기 ↗" },
  data: { icon: "📎", label: "데이터", open: "원문 열기 ↗" },
};

export function SourceCard({ c }: { c: Citation }) {
  const kind = c.kind && KIND_META[c.kind] ? c.kind : "data";
  const meta = KIND_META[kind];
  const fresh = c.freshness ? FRESH_LABEL[c.freshness] || c.freshness : null;
  return (
    <div className={`scard ${kind}`}>
      <div className="scard-head">
        {c.index ? <span className="cnum">[{c.index}]</span> : null}
        <span className="sicon" aria-hidden>{meta.icon}</span>
        <span className="ssource">{c.source || "출처"}</span>
        {c.doc_type && c.doc_type !== "news" ? <span className="sdoc mono">{c.doc_type}</span> : null}
        <FreshnessDot f={c.freshness} />
      </div>
      {(c.as_of || c.page) && (
        <div className="scard-sub mono">
          {c.as_of ? <span>{c.as_of}</span> : null}
          {c.page ? <span title="문서 위치/접수번호">{c.page}</span> : null}
        </div>
      )}
      {c.snippet ? (
        <div className="scard-snip">{kind === "filing" || kind === "news" ? `“${c.snippet}”` : c.snippet}</div>
      ) : null}
      <div className="scard-trust mono">
        <FreshnessDot f={c.freshness} />
        {fresh ? <span>{fresh}</span> : <span>출처 표시됨</span>}
        {c.ticker ? <span className="stick">· {c.ticker}</span> : null}
      </div>
      {kind === "news" ? <div className="snote">ⓘ 맥락 정보 — 전망/점수 아님</div> : null}
      {c.url ? <a className="scard-open" href={c.url} target="_blank" rel="noreferrer">{meta.open}</a> : null}
    </div>
  );
}

// Compact inline chip used under a message ([n] + source + freshness dot).
export function CiteChip({ c }: { c: Citation }) {
  const meta = (c.kind && KIND_META[c.kind]) || KIND_META.data;
  const body = (
    <>
      {c.index ? <span className="cnum">[{c.index}]</span> : null}
      <span aria-hidden>{meta.icon}</span> {c.source || "출처"}
      <FreshnessDot f={c.freshness} />
    </>
  );
  return c.url ? (
    <a className="cite-chip" href={c.url} target="_blank" rel="noreferrer" title={c.snippet || c.url}>{body}</a>
  ) : (
    <span className="cite-chip" title={c.snippet || ""}>{body}</span>
  );
}
