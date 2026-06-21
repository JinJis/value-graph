"use client";

// Click-to-expand full source viewer — wireframe "화면 상세" Screen 08. A preview in the
// Live Context panel expands into this modal: the source rendered in its native full form
// with the cited passage highlighted + a margin pin, and a right "이 원문을 인용한 곳"
// context panel (freshness / as_of / source) with jump-back + copy-citation actions.
// Honest by construction: we render the extracted passage we actually hold, never a
// fabricated full document.

import { useState } from "react";
import { Citation, sourceShape, hostOf, SrcTable, evidenceSrc, evidenceDocSrc } from "./SourceCard";
import { FreshnessDot, FRESH_LABEL } from "./ui";

const TABS: { key: "filing" | "web" | "data"; label: string }[] = [
  { key: "filing", label: "📄 공시" },
  { key: "web", label: "🌐 뉴스" },
  { key: "data", label: "▤ 데이터" },
];

export function SourceViewer({ c, onClose }: { c: Citation; onClose: () => void }) {
  const shape = sourceShape(c);
  const [copied, setCopied] = useState(false);
  const [imgFailed, setImgFailed] = useState(false);
  const [imgOk, setImgOk] = useState(false);
  const fresh = c.freshness ? FRESH_LABEL[c.freshness] || c.freshness : null;
  // PH-PROV2: the deterministic highlighted screenshot of the filing line (fetched lazily;
  // falls back to the text rendering below on 204 / error — never fabricated).
  const evSrc = evidenceSrc(c.evidence_image_url);
  // PH-PROV3: if the highlight loaded, the real PDF exists → "원문 열기" opens it.
  const docSrc = evidenceDocSrc(c.evidence_image_url);

  async function copyCite() {
    const text = `“${c.snippet ?? ""}” — ${c.source ?? ""}${c.as_of ? ` (${c.as_of})` : ""}${c.url ? ` ${c.url}` : ""}`.trim();
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch {}
  }

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="sv" onClick={(e) => e.stopPropagation()}>
        <div className="sv-head">
          <div className="sv-tabs">
            {TABS.map((t) => <span key={t.key} className={`sv-tab ${t.key === shape ? "on" : ""}`}>{t.label}</span>)}
          </div>
          <span className="sv-name">{c.source || "원문"}</span>
          {c.page ? <span className="sv-meta mono">{c.page}{c.doc_type ? ` · ${c.doc_type}` : ""}</span> : null}
          <button className="sv-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="sv-body">
          <div className="sv-stage">
            {evSrc && !imgFailed && (
              <figure className="sv-evidence">
                <img className="sv-evidence-img" src={evSrc} loading="lazy"
                     alt="원문에서 인용 부분 하이라이트"
                     onLoad={() => setImgOk(true)} onError={() => setImgFailed(true)} />
                <figcaption className="sv-evidence-cap mono">📷 실제 공시 원문 · 노란 박스가 인용한 수치</figcaption>
              </figure>
            )}
            {shape === "filing" && (
              <article className="sv-page">
                <div className="sv-page-hd mono">{c.source || "공시 문서"}{c.page ? ` · ${c.page}` : ""}</div>
                {c.doc_type && c.doc_type !== "news" ? <h4 className="sv-page-h">{c.doc_type}</h4> : null}
                <p className="sv-skel-l" /><p className="sv-skel-l" style={{ width: "88%" }} />
                <div className="sv-quote">
                  <span className="sv-pin mono">{c.index ?? "1"}</span>
                  {c.snippet || "인용된 원문 구절을 불러올 수 없습니다."}
                </div>
                <p className="sv-skel-l" style={{ width: "94%" }} /><p className="sv-skel-l" style={{ width: "70%" }} />
              </article>
            )}
            {shape === "web" && (
              <article className="sv-web">
                <div className="sp-chrome">
                  <span className="sp-dots" aria-hidden><i /><i /><i /></span>
                  <span className="sp-url mono">🔒 {hostOf(c.url) || c.source || "web"}</span>
                </div>
                <div className="sv-web-body">
                  <h4 className="sv-headline">{c.source || hostOf(c.url) || "기사"}</h4>
                  {c.as_of ? <div className="sv-wmeta mono">{c.as_of}</div> : null}
                  <p className="sv-skel-l" />
                  <p className="sv-web-text">“<mark>{c.snippet || "인용 구절"}</mark>”</p>
                  <p className="sv-skel-l" style={{ width: "82%" }} />
                </div>
              </article>
            )}
            {shape === "data" && (
              <article className="sv-page">
                <div className="sv-page-hd mono">{c.source || "추출 데이터"}{c.ticker ? ` · ${c.ticker}` : ""}</div>
                {c.table ? <SrcTable table={c.table} /> : null}
                {c.snippet ? (
                  <div className="sv-data mono">
                    <span className="sv-pin mono">{c.index ?? "1"}</span>
                    {c.snippet}
                  </div>
                ) : null}
                <p className="sv-data-note mono">{c.as_of ? `as_of ${c.as_of} · ` : ""}출처에서 추출·계산된 값 (셀 = 인용 근거)</p>
              </article>
            )}
          </div>

          <aside className="sv-ctx">
            <div className="sv-ctx-h mono">이 원문을 인용한 곳</div>
            <div className="sv-ctx-card">
              <div className="sv-ctx-snip">{c.snippet ? `“${c.snippet}”` : "이 답변이 인용한 출처입니다."}</div>
              {c.index ? <div className="sv-ctx-n mono">인용 [{c.index}]</div> : null}
            </div>
            <div className="sv-ctx-meta mono">
              <div><FreshnessDot f={c.freshness} /> 신선도 {fresh ?? "—"}</div>
              {c.as_of ? <div>as_of {c.as_of}</div> : null}
              {c.ticker ? <div>{c.ticker}</div> : null}
              {c.page ? <div>{c.page}</div> : null}
            </div>
            <div className="sv-ctx-actions">
              {imgOk && docSrc ? (
                <a className="sv-act primary" href={docSrc} target="_blank" rel="noreferrer">원문 PDF 열기 ↗</a>
              ) : c.url ? (
                <a className="sv-act primary" href={c.url} target="_blank" rel="noreferrer">원문 열기 ↗</a>
              ) : null}
              <button className="sv-act" onClick={copyCite}>{copied ? "복사됨 ✓" : "인용 복사"}</button>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
