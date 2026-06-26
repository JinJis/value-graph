"""The "라이브 데모" dashboard template — a rich, self-contained showcase of what the platform can
surface, with realistic MOCK data embedded directly in each widget's spec (no `tool` → renders
statically, never re-fetches). Mirrors a Datadog-style board: dense, varied tiles, professional.

Every widget is a normal pin spec (the same shape the agent emits), so it renders through the real
ArtifactCard / SourceCard pipeline. Data is generated deterministically at import (seed time) so the
dates roll forward to "now" while the shape stays stable.

Covers: price candles (sourced event markers + 52주 밴드) · 매출/영업이익 추이 · 밸류에이션·투자지표·
수급 KPI · 실시간 뉴스 피드 · 공시 알림 · Peer 밸류 비교 · 거시 지표 · 종목 내러티브 · DCF 내재가치.
"""

from __future__ import annotations

import datetime
import random

_SEED = 20260626
_TODAY = datetime.date.today()


def _weekdays(n: int, end: datetime.date) -> list[datetime.date]:
    out: list[datetime.date] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return list(reversed(out))


def _round100(x: float) -> int:
    return int(round(x / 100.0) * 100)


def _price_candles() -> tuple[list[dict], list[dict], int, int, int]:
    """A realistic ~3-month daily KRW candle series (deterministic). Returns
    (candles, close-series points, latest_close, 52w_high, 52w_low)."""
    rng = random.Random(_SEED)
    days = _weekdays(62, _TODAY - datetime.timedelta(days=1))
    candles: list[dict] = []
    points: list[dict] = []
    close = 73000.0
    target = 78500.0   # gentle pull toward a realistic level keeps the walk in a believable band
    for d in days:
        drift = (target - close) / close * 0.04 + rng.uniform(-0.013, 0.013)
        new_close = close * (1 + drift)
        open_ = close * (1 + rng.uniform(-0.006, 0.006))
        hi = max(open_, new_close) * (1 + rng.uniform(0.001, 0.011))
        lo = min(open_, new_close) * (1 - rng.uniform(0.001, 0.011))
        vol = rng.randint(7, 17) * 1_000_000
        iso = d.isoformat()
        candles.append({"time": iso, "open": _round100(open_), "high": _round100(hi),
                        "low": _round100(lo), "close": _round100(new_close), "volume": vol})
        points.append({"x": iso, "y": _round100(new_close)})
        close = new_close
    closes = [c["close"] for c in candles]
    hi52 = _round100(max(closes) * 1.10)
    lo52 = _round100(min(closes) * 0.90)
    return candles, points, candles[-1]["close"], hi52, lo52


def _quarters(n: int) -> list[str]:
    y, q = _TODAY.year, (_TODAY.month - 1) // 3 + 1
    out: list[str] = []
    for _ in range(n):
        out.append(f"{y}-Q{q}")
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return list(reversed(out))


def _revenue_series() -> list[dict]:
    """삼성전자-규모 분기 매출/영업이익 (raw KRW). Realistic ₩70-83조 매출 · ₩4-14조 영업이익."""
    qs = _quarters(11)
    rev = [73.6, 76.8, 77.8, 79.3, 71.9, 74.1, 79.0, 81.5, 77.0, 82.9, 79.8]
    op = [4.8, 6.7, 8.9, 10.7, 6.6, 8.4, 10.4, 12.9, 9.1, 13.6, 11.2]
    return [
        {"label": "매출", "points": [{"x": q, "y": v * 1e12} for q, v in zip(qs, rev)]},
        {"label": "영업이익", "points": [{"x": q, "y": v * 1e12} for q, v in zip(qs, op)]},
    ]


def _ago(hours: float) -> str:
    if hours < 1:
        return f"{int(hours * 60)}분 전"
    if hours < 24:
        return f"{int(hours)}시간 전"
    return (_TODAY - datetime.timedelta(days=int(hours // 24))).strftime("%m-%d")


def demo_template() -> dict:
    candles, close_pts, last, hi52, lo52 = _price_candles()
    today = _TODAY.isoformat()
    intrinsic = _round100(last * 1.14)   # DCF result, kept ~+14% over the latest price for consistency
    # a sourced earnings marker + ex-dividend marker on the price chart
    mk1 = candles[len(candles) * 2 // 3]["time"]
    mk2 = candles[len(candles) // 3]["time"]

    widgets = [
        # ── Row 1: 주가 차트 + 실적 추이 ──────────────────────────────────────────────
        {"cols": 2, "spec": {
            "kind": "candlestick", "title": "삼성전자 주가 (005930)", "source": "Yahoo Finance",
            "ticker": "005930.KS", "as_of": today, "freshness": "fresh", "cadence": "daily",
            "category": "market", "candles": candles,
            "series": [{"label": "종가", "points": close_pts}],
            "pricelines": [{"price": hi52, "label": "52주 최고"}, {"price": lo52, "label": "52주 최저"}],
            "markers": [
                {"time": mk1, "label": "1분기 실적발표", "kind": "earnings", "position": "aboveBar"},
                {"time": mk2, "label": "배당락", "kind": "dividend", "position": "belowBar"},
            ]}},
        {"cols": 2, "spec": {
            "kind": "timeseries", "title": "삼성전자 매출·영업이익 (분기)", "source": "OpenDART (FSS)",
            "ticker": "005930.KS", "as_of": "%s-Q%d" % (_TODAY.year, (_TODAY.month - 1) // 3),
            "freshness": "fresh", "cadence": "event", "category": "fundamentals",
            "chart_style": "bar", "series": _revenue_series()}},

        # ── Row 2: 밸류에이션 · 투자지표 · 수급 KPI ──────────────────────────────────
        {"cols": 1, "spec": {
            "kind": "kpi", "title": "밸류에이션", "source": "OpenDART · Yahoo",
            "ticker": "005930.KS", "as_of": today, "freshness": "fresh", "cadence": "daily",
            "category": "valuation", "table": [
                ["지표", "값", "업종평균", "평가"],
                ["PER", "11.8배", "14.5배", "저평가"],
                ["PBR", "1.32배", "1.6배", "저평가"],
                ["배당수익률", "2.6%", "1.9%", "우수"],
                ["EV/EBITDA", "4.9배", "6.8배", "저평가"],
                ["ROE", "9.8%", "8.1%", "양호"],
            ]}},
        {"cols": 1, "spec": {
            "kind": "kpi", "title": "투자 지표", "source": "Yahoo · KRX",
            "ticker": "005930.KS", "as_of": today, "freshness": "fresh", "cadence": "intraday",
            "category": "market", "table": [
                ["지표", "값"],
                ["현재가", f"{last:,}원"],
                ["52주 변동", f"{lo52:,} ~ {hi52:,}"],
                ["시가총액", "약 460조원"],
                ["외국인 보유", "54.2%"],
                ["거래대금(일)", "약 1.1조원"],
            ]}},
        {"cols": 1, "spec": {
            "kind": "kpi", "title": "수급 동향 (5거래일 누적)", "source": "KIS",
            "ticker": "005930.KS", "as_of": today, "freshness": "fresh", "cadence": "daily",
            "category": "market", "table": [
                ["투자자", "순매수", "추세"],
                ["외국인", "+8,420억", "5일 연속 매수"],
                ["기관", "+2,160억", "순매수"],
                ["개인", "−10,580억", "순매도"],
                ["연기금", "+1,340억", "순매수"],
            ]}},

        # ── Row 3: 실시간 뉴스 + 공시 알림 ──────────────────────────────────────────
        {"cols": 2, "spec": {
            "kind": "table", "title": "📰 실시간 뉴스 피드", "source": "Google News",
            "as_of": today, "freshness": "fresh", "cadence": "streaming", "category": "news",
            "table": [
                ["시각", "헤드라인", "매체"],
                [_ago(0.3), "삼성전자, HBM3E 12단 양산 본격화…AI 가속기 공급 확대", "전자신문"],
                [_ago(1.5), "메모리 현물가 3주 연속 반등…DDR5 강세 지속", "Reuters"],
                [_ago(3), "외국인, 반도체株 5거래일 연속 순매수", "한국경제"],
                [_ago(6), "美 필라델피아 반도체지수(SOX) 사상 최고", "Bloomberg"],
                [_ago(20), "삼성 파운드리, 2나노 시험양산 진입", "조선비즈"],
                [_ago(28), "SK하이닉스 'HBM 수요 내년까지 견조'", "연합뉴스"],
            ]}},
        {"cols": 2, "spec": {
            "kind": "table", "title": "🔔 공시 알림", "source": "OpenDART (FSS)",
            "as_of": today, "freshness": "fresh", "cadence": "event", "category": "filings",
            "table": [
                ["시각", "종목", "공시", "상태"],
                [_ago(2), "삼성전자", "단일판매·공급계약체결", "🔴 NEW"],
                [_ago(5), "삼성전자", "자기주식취득 결정", "🔴 NEW"],
                [_ago(26), "SK하이닉스", "주요사항보고서(유상증자)", "읽음"],
                [_ago(27), "삼성전자", "임원·주요주주 특정증권 소유보고", "읽음"],
                [_ago(50), "현대차", "현금·현물배당 결정", "읽음"],
                [_ago(72), "삼성전자", "분기보고서 (1분기)", "읽음"],
            ]}},

        # ── Row 4: Peer 밸류 비교 + 거시 지표 ───────────────────────────────────────
        {"cols": 2, "spec": {
            "kind": "table", "title": "반도체 Peer 밸류 비교", "source": "SEC EDGAR · OpenDART",
            "as_of": today, "freshness": "fresh", "cadence": "daily", "category": "valuation",
            "table": [
                ["기업", "주가", "PER", "PBR", "배당", "시가총액"],
                ["삼성전자", f"{last:,}원", "11.8배", "1.32배", "2.6%", "460조원"],
                ["SK하이닉스", "212,000원", "8.4배", "2.1배", "1.1%", "154조원"],
                ["TSMC", "$214", "27.5배", "7.8배", "1.4%", "$1.11T"],
                ["Micron", "$142", "19.2배", "3.1배", "0.3%", "$158B"],
                ["Intel", "$26", "—", "0.9배", "1.6%", "$112B"],
            ]}},
        {"cols": 2, "spec": {
            "kind": "table", "title": "거시 지표", "source": "FRED · ECOS",
            "as_of": today, "freshness": "fresh", "cadence": "scheduled", "category": "macro",
            "table": [
                ["지표", "현재", "전월", "추세"],
                ["한국 기준금리", "2.75%", "2.75%", "→ 동결"],
                ["미국 기준금리(상단)", "4.50%", "4.50%", "→ 동결"],
                ["원/달러 환율", "1,362원", "1,378원", "↘ 원화강세"],
                ["미 10년 국채", "4.21%", "4.34%", "↘ 하락"],
                ["미 CPI(YoY)", "2.8%", "3.0%", "↘ 둔화"],
                ["KOSPI", "2,684", "2,611", "↗ 상승"],
            ]}},

        # ── Row 5: 종목 내러티브 + DCF 내재가치 ──────────────────────────────────────
        {"cols": 2, "spec": {
            "kind": "narrative", "title": "삼성전자 종목 내러티브", "source": "자체 분석 (사실 기반)",
            "as_of": today, "freshness": "fresh", "cadence": "one_shot", "category": "fundamentals",
            "sections": [
                {"heading": "사업 구조", "body": "메모리(DRAM·NAND)·시스템LSI·파운드리의 DS부문과 MX(모바일)·"
                 "VD(가전) 부문으로 구성. 메모리가 영업이익의 큰 축이며, HBM·DDR5 등 고부가 제품 비중 확대가 "
                 "이익 레버리지의 핵심."},
                {"heading": "투자 포인트", "body": "① AI 가속기향 HBM 수요 구조적 성장 ② 메모리 업황 회복 사이클 "
                 "진입 ③ 자사주 매입·배당 등 주주환원 확대 ④ 파운드리 2나노 로드맵."},
                {"heading": "밸류에이션", "body": f"현재가 {last:,}원, PER 11.8배는 업종평균(14.5배) 대비 할인. "
                 "PBR 1.32배·EV/EBITDA 4.9배로 역사적 밴드 하단. (전망·목표가 아님 — 사실 기반 요약)"},
                {"heading": "리스크", "body": "메모리 가격 변동성, 중국 수요 둔화, 환율, 파운드리 가동률 등."},
            ]}},
        {"cols": 2, "spec": {
            "kind": "table", "title": "DCF 내재가치 (가정 기반 · 예측 아님)", "source": "재무제표 기반 모델",
            "ticker": "005930.KS", "as_of": today, "freshness": "fresh", "cadence": "one_shot",
            "category": "valuation",
            "table": [
                ["연차", "예상 FCF", "현재가치(PV)"],
                ["1년차", "32.4조", "29.5조"],
                ["2년차", "35.0조", "29.0조"],
                ["3년차", "37.8조", "28.4조"],
                ["4년차", "40.8조", "27.9조"],
                ["5년차", "44.1조", "27.4조"],
                ["내재가치 / 주", f"{intrinsic:,}원", "현재가 +14%"],
            ],
            "computation": {
                "method": "2단계 FCF 할인 (DCF)",
                "formula": "EV = Σ PV(FCFₜ) + PV(터미널) · 자기자본가치 = EV − 순부채 · 내재가치 = ÷ 발행주식수",
                "inputs": [
                    {"label": "기준 FCF", "value": "30.0조", "source": "OpenDART FY 현금흐름표"},
                    {"label": "발행주식수", "value": "59.7억주", "source": "OpenDART"},
                    {"label": "순부채", "value": "−92조 (순현금)", "source": "OpenDART 재무상태표"},
                ],
                "assumptions": [
                    {"label": "성장률", "value": "8.0%"}, {"label": "할인율", "value": "9.5%"},
                    {"label": "추정기간", "value": "5년"}, {"label": "영구성장률", "value": "2.5%"},
                ],
                "steps": [
                    {"label": "추정기간 PV 합", "value": "142.2조"},
                    {"label": "터미널 PV", "value": "373.8조"},
                    {"label": "자기자본가치", "value": "608.0조"},
                ],
                "note": "사용자 가정 기반 계산이며 예측·목표가가 아닙니다.",
            }}},
    ]
    return {
        "id": "dt_demo",
        "name": "⭐ 라이브 데모 — 삼성전자",
        "market": None,
        "description": "11 위젯 · 주가·실적·밸류·뉴스·공시·거시 (데모 데이터)",
        "widgets": widgets,
    }
