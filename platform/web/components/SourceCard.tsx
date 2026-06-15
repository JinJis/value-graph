"use client";

// PH-4/U2: the type-aware source-preview card + the one shared trust legend.
// A citation renders differently by `kind` (filing verbatim-span / metric
// computation / news snippet), and every figure shows a freshness signal — the
// "trust by construction" brand, not fine print.

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

const FRESH_LABEL: Record<string, string> = {
  fresh: "최신 (30일 이내)",
  aging: "갱신 권장",
  stale: "오래됨",
  gap: "공백",
};

const KIND_META: Record<string, { icon: string; label: string }> = {
  filing: { icon: "📄", label: "공시" },
  news: { icon: "📰", label: "뉴스" },
  metric: { icon: "📊", label: "지표" },
  data: { icon: "📎", label: "데이터" },
};

export function FreshnessDot({ f }: { f?: string }) {
  if (!f) return null;
  const label = FRESH_LABEL[f] || f;
  return <span className={`fdot ${f}`} title={label} aria-label={label} />;
}

// One legend, reused everywhere a freshness dot appears (the signature legend).
export function TrustLegend() {
  return (
    <div className="legend" aria-label="신선도 범례">
      <span><i className="fdot fresh" /> 최신</span>
      <span><i className="fdot aging" /> 갱신 권장</span>
      <span><i className="fdot stale" /> 오래됨</span>
    </div>
  );
}

export function SourceCard({ c }: { c: Citation }) {
  const kind = c.kind && KIND_META[c.kind] ? c.kind : "data";
  const meta = KIND_META[kind];
  return (
    <div className={`scard ${kind}`}>
      <div className="scard-head">
        {c.index ? <span className="cnum">[{c.index}]</span> : null}
        <span className="sicon" aria-hidden>{meta.icon}</span>
        <span className="ssource">{c.source || "출처"}</span>
        {c.doc_type && c.doc_type !== "news" ? <span className="sdoc mono">{c.doc_type}</span> : null}
        <FreshnessDot f={c.freshness} />
      </div>
      {c.snippet ? (
        <div className="scard-snip">{kind === "filing" ? `“${c.snippet}”` : c.snippet}</div>
      ) : null}
      <div className="scard-foot">
        {c.ticker ? <span className="mono stick">{c.ticker}</span> : null}
        {c.as_of ? <span className="mono">as of {c.as_of}</span> : null}
        {c.page ? <span className="spage mono" title="문서 위치/접수번호">{c.page}</span> : null}
        {c.url ? <a className="slink" href={c.url} target="_blank" rel="noreferrer">원문 ↗</a> : null}
      </div>
      {kind === "news" ? <div className="snote">맥락 정보 — 전망 아님</div> : null}
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
