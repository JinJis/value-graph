"use client";

// 위젯 추가 갤러리 — wireframe 04. 3-pane: 카테고리(9, from /api/connectors) → 소스/지표 목록 →
// 설정·미리보기 + "이 위젯에 알림" 토글. Sources come from the datasets /catalog (never hardcoded).
// Adding creates a pin (a dashboard widget) carrying the tool+args+viz; if the alert toggle is on,
// the parent opens the alert sheet bound to the new widget.

import { useEffect, useMemo, useState } from "react";
import { Button, FreshnessDot } from "./ui";

type Tool = { name: string; label: string; description?: string; source?: string; markets?: string[]; connector_name?: string };
type Cat = { id: string; label: string; description?: string; tools: Tool[] };

const VIZ: { key: string; label: string; kind: string; chart_style?: string }[] = [
  { key: "line", label: "라인", kind: "timeseries", chart_style: "line" },
  { key: "value", label: "숫자", kind: "kpi" },
  { key: "spark", label: "스파크", kind: "timeseries" },
  { key: "table", label: "표", kind: "table" },
];

export type AddedWidget = { pinId: string; spec: any; withAlert: boolean };

export default function WidgetGallery({
  boardId, boardName, onClose, onAdded,
}: {
  boardId: string;
  boardName?: string;
  onClose: () => void;
  onAdded: (w: AddedWidget) => void;
}) {
  const [cats, setCats] = useState<Cat[]>([]);
  const [catId, setCatId] = useState<string>("");
  const [tool, setTool] = useState<Tool | null>(null);
  const [viz, setViz] = useState("line");
  const [target, setTarget] = useState("");
  const [withAlert, setWithAlert] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/connectors");
        const cs = (r.ok ? (await r.json()).categories : []) as Cat[];
        setCats(cs);
        if (cs.length) setCatId(cs[0].id);
      } catch {} finally { setLoading(false); }
    })();
  }, []);

  const cat = useMemo(() => cats.find((c) => c.id === catId) ?? null, [cats, catId]);
  const vizMeta = VIZ.find((v) => v.key === viz) ?? VIZ[0];

  function buildSpec(): any {
    const t = target.trim();
    const args: any = {};
    if (t) {
      args.ticker = t;
      if (/^\d/.test(t)) args.market = "KR"; else args.market = "US";
    }
    const spec: any = {
      kind: vizMeta.kind, title: tool?.label || tool?.name || "위젯",
      source: tool?.source || tool?.connector_name, viz,
      tool: tool?.name, args,
    };
    if (vizMeta.chart_style) spec.chart_style = vizMeta.chart_style;
    return spec;
  }

  async function add() {
    if (!tool) return;
    setBusy(true);
    try {
      const spec = buildSpec();
      const r = await fetch("/api/board", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec, board_ids: [boardId] }),
      });
      if (!r.ok) throw new Error();
      const pin = (await r.json()).pinned?.[0];
      // populate live data best-effort (honest gap if the tool can't refresh)
      if (pin?.id) { try { await fetch(`/api/board/${pin.id}/refresh`, { method: "POST" }); } catch {} }
      onAdded({ pinId: pin?.id, spec, withAlert });
    } catch { setBusy(false); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal widget-gallery" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>위젯 추가</h3>
          <button className="x" onClick={onClose} aria-label="닫기">✕</button>
        </div>
        <div className="wg-sub">대시보드{boardName ? `: ${boardName}` : ""} · 지원하는 모든 데이터 소스</div>

        <div className="wg-body">
          {/* categories */}
          <div className="wg-cats">
            {loading && <div className="muted-note">불러오는 중…</div>}
            {cats.map((c) => (
              <button key={c.id} type="button" className={`wg-cat ${c.id === catId ? "on" : ""}`}
                onClick={() => { setCatId(c.id); setTool(null); }}>{c.label}</button>
            ))}
            {!loading && cats.length === 0 && <div className="muted-note">카탈로그를 불러올 수 없어요.</div>}
          </div>

          {/* source list */}
          <div className="wg-sources">
            {cat && <div className="wg-cat-desc">{cat.label}{cat.description ? ` · ${cat.description}` : ""}</div>}
            {(cat?.tools ?? []).map((t) => (
              <button key={t.name} type="button" className={`wg-source ${tool?.name === t.name ? "on" : ""}`}
                onClick={() => setTool(t)}>
                <FreshnessDot f="fresh" />
                <span className="wg-source-label">{t.label}</span>
                <span className="wg-source-badge mono">{t.source || t.connector_name}</span>
              </button>
            ))}
            {cat && cat.tools.length === 0 && <div className="muted-note">이 카테고리에 도구가 없어요.</div>}
          </div>

          {/* config + preview */}
          <div className="wg-config">
            <div className="wg-cfg-l">위젯 설정</div>
            {!tool && <div className="muted-note">왼쪽에서 데이터 소스를 선택하세요.</div>}
            {tool && (
              <>
                <div className="wg-field-l">시각화</div>
                <div className="wg-viz">
                  {VIZ.map((v) => (
                    <button key={v.key} type="button" className={`wg-viz-btn ${viz === v.key ? "on" : ""}`} onClick={() => setViz(v.key)}>{v.label}</button>
                  ))}
                </div>
                <div className="wg-field-l">대상 <span className="muted-note">(선택 · 티커/심볼)</span></div>
                <input className="input" value={target} placeholder="예: 005930.KS · AAPL" onChange={(e) => setTarget(e.target.value)} />

                <div className="wg-preview">
                  <div className="wg-prev-head">{tool.label}<span className="wg-prev-src mono">{tool.source || tool.connector_name}</span><FreshnessDot f="fresh" /></div>
                  <div className="wg-prev-ph">{vizMeta.label} · 미리보기</div>
                  <div className="wg-prev-foot mono">출처: {tool.source || tool.connector_name} · as_of —</div>
                </div>

                <label className="wg-alert">
                  <span>🔔 이 위젯에 알림</span>
                  <input type="checkbox" checked={withAlert} onChange={(e) => setWithAlert(e.target.checked)} />
                </label>
              </>
            )}
          </div>
        </div>

        <div className="modal-foot">
          <span className="grow" />
          <Button variant="ghost" onClick={onClose} disabled={busy}>취소</Button>
          <Button onClick={add} disabled={busy || !tool}>{busy ? "추가 중…" : "대시보드에 추가"}</Button>
        </div>
      </div>
    </div>
  );
}
