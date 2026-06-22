"use client";

import { useRef, useState } from "react";
import { Artifact, ArtifactCard } from "./ArtifactCard";
import { Citation, SourceCard } from "./SourceCard";
import { Button } from "./ui";

// PH-DATA-5 / PH-9: the 지표(KPI) desk — pick a company, pull its REPORTED KPIs straight
// from the filing-text corpus. Every KPI is cited to (and highlighted in) the real filing
// passage; no forecasts (guardrail). The card pins to the Board; each KPI's source opens
// in the same evidence viewer used across the app. Honest when nothing is indexed yet.

type SearchResult = { name?: string; ticker?: string; market?: string; cik?: string };
type KpiResp = {
  ticker: string; market: string; kpis: any[];
  citations: Citation[]; artifact: Artifact | null; note?: string;
};

export default function KpiPanel(
  { onPin, onExpand }: { onPin: (a: Artifact) => void; onExpand: (c: Citation) => void },
) {
  const [market, setMarket] = useState("US");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [picked, setPicked] = useState<SearchResult | null>(null);
  const [data, setData] = useState<KpiResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  function runSearch(q: string) {
    setQuery(q);
    setPicked(null);
    if (debounce.current) clearTimeout(debounce.current);
    if (!q.trim()) { setResults([]); return; }
    debounce.current = setTimeout(async () => {
      try {
        const r = await fetch(`/api/company/search?q=${encodeURIComponent(q)}&market=${market}`);
        if (r.ok) setResults((await r.json()).results ?? []);
      } catch {}
    }, 220);
  }

  async function fetchKpis(res: SearchResult) {
    if (!res.ticker) return;
    setPicked(res);
    setResults([]);
    setQuery(res.name || res.ticker);
    setBusy(true);
    setErr("");
    setData(null);
    try {
      const r = await fetch("/api/kpis", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: res.ticker, market: res.market ?? market }),
      });
      if (!r.ok) { setErr("지표를 가져오지 못했어요. 잠시 후 다시 시도해 주세요."); return; }
      setData(await r.json());
    } catch { setErr("지표를 가져오지 못했어요. 잠시 후 다시 시도해 주세요."); }
    finally { setBusy(false); }
  }

  return (
    <div className="kpi-view">
      <div className="kpi-head">
        <h3>📈 지표 (KPI)</h3>
        <span className="sub">공시 원문에서 추출한 <b>보고 지표</b> — 각 수치는 실제 공시에 인용·하이라이트 · 전망/추정 없음</span>
      </div>

      <div className="kpi-search">
        <div className="seg">
          {["US", "KR"].map((m) => (
            <button key={m} className={market === m ? "on" : ""} onClick={() => setMarket(m)}>{m}</button>
          ))}
        </div>
        <div className="kpi-searchbox">
          <input className="input" value={query} placeholder="회사명·티커 검색 (예: Apple, AAPL, 삼성전자)"
            onChange={(e) => runSearch(e.target.value)} />
          {results.length > 0 && (
            <div className="kpi-results">
              {results.map((r) => (
                <button key={`${r.market}:${r.ticker}`} className="kpi-result" onMouseDown={(e) => { e.preventDefault(); fetchKpis(r); }}>
                  <span className="nm">{r.name || r.ticker}</span>
                  <span className="tk mono">{r.market} · {r.ticker}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {picked && <Button variant="ghost" size="sm" disabled={busy} onClick={() => fetchKpis(picked)}>{busy ? "…" : "↻ 다시"}</Button>}
      </div>

      {!picked && !data && (
        <p className="kpi-empty">회사를 검색해 선택하면, 최신 공시에서 보고된 핵심 지표를 <b>원문 근거</b>와 함께 보여드려요. 추정·전망은 제공하지 않습니다.</p>
      )}
      {busy && <p className="kpi-empty">{query} 지표를 공시에서 추출하는 중…</p>}
      {err && <p className="kpi-empty err">{err}</p>}

      {data && !busy && (
        <div className="kpi-result-body">
          {data.artifact ? (
            <ArtifactCard a={data.artifact} onPin={() => data.artifact && onPin(data.artifact)} />
          ) : (
            <p className="kpi-empty">{data.note || "이 회사의 공시 텍스트가 아직 색인되지 않았어요."}</p>
          )}
          {(data.citations?.length || 0) > 0 && (
            <section className="kpi-evidence">
              <div className="kpi-ev-head">
                <h4>인용 원문 {data.artifact ? "(KPI별 근거)" : "(색인된 공시 문단)"}</h4>
                <span className="live-label">⛔ 점수·전망 없음 · 인용한 <b>원문 그대로</b></span>
              </div>
              <div className="kpi-ev-grid">
                {data.citations.map((c, i) => <SourceCard key={i} c={c} onExpand={onExpand} />)}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
