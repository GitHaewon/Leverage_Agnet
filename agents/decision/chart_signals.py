"""
Chart signal scoring — 결정적 차트 시그널 점수화.

규칙:
  - AI 호출 없음. 주문 없음. 순수 점수 함수.
  - 단일 지표만으로 방향 점수를 크게 만들지 않는다.
  - 시장 국면에 따라 같은 지표도 다르게 해석한다.
"""
from __future__ import annotations

from typing import Any

from agents.decision.models import MarketRegime, MarketRegimeResult, SignalScore

_PRIMARY_TF_ORDER = ("1h", "4h", "15m", "5m", "1d")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _cfg(config: dict | None, key: str, default: float) -> float:
    return float(config.get(key, default)) if config and key in config else default


def _as_regime(market_regime: Any) -> MarketRegime:
    if isinstance(market_regime, MarketRegimeResult):
        return market_regime.regime
    if isinstance(market_regime, MarketRegime):
        return market_regime
    try:
        return MarketRegime(str(market_regime))
    except ValueError:
        return MarketRegime.UNKNOWN


def _select_primary_tf(technical_result: Any) -> Any | None:
    if technical_result is None:
        return None
    analyses: dict = getattr(technical_result, "analyses", {}) or {}
    if not analyses:
        return None
    for tf in _PRIMARY_TF_ORDER:
        if tf in analyses:
            return analyses[tf]
    return next(iter(analyses.values()))


def _current_price(technical_result: Any, primary: Any | None, market_data: dict) -> float:
    for value in (
        market_data.get("current_price"),
        market_data.get("price"),
        getattr(technical_result, "latest_close", None),
        getattr(primary, "close", None),
    ):
        if value is not None:
            return float(value)
    return 0.0


def _recent_price_change(market_data: dict) -> float:
    for key in (
        "recent_price_change_pct",
        "price_change_pct",
        "price_change_1h_pct",
        "price_change_5m_pct",
    ):
        if key in market_data and market_data[key] is not None:
            return float(market_data[key])
    return 0.0


def _near_level(
    price: float,
    levels: list[float],
    threshold_pct: float,
) -> tuple[bool, float | None]:
    if price <= 0:
        return False, None
    for level in levels:
        distance_pct = abs(price - float(level)) / price * 100
        if distance_pct <= threshold_pct:
            return True, float(level)
    return False, None


def _add(
    scores: dict[str, float],
    evidence: dict[str, int],
    side: str,
    points: float,
    reason: str,
    reasons: list[str],
) -> None:
    scores[side] += points
    evidence[side] += 1
    reasons.append(reason)


def score_chart_signals(
    market_regime: Any,
    technical_result: Any,
    market_data: dict | None,
    config: dict | None = None,
) -> SignalScore:
    """
    차트 기반 방향 점수를 계산한다.

    Parameters
    ----------
    market_regime:     MarketRegime 또는 MarketRegimeResult.
    technical_result:  TechnicalAnalysisResult duck type.
    market_data:       current_price, recent_price_change_pct 등 선택 필드.
    config:            임계값 오버라이드 dict.

    Returns
    -------
    SignalScore(long_score, short_score, no_trade_score, risk_score, reasons)
    """
    regime = _as_regime(market_regime)
    data = market_data or {}
    primary = _select_primary_tf(technical_result)
    price = _current_price(technical_result, primary, data)
    price_change = _recent_price_change(data)

    near_level_pct = _cfg(config, "near_level_pct", 0.8)
    volume_spike_ratio = _cfg(config, "volume_spike_ratio", 1.8)
    conflict_penalty = _cfg(config, "conflict_no_trade_bonus", 20.0)

    scores = {"long": 0.0, "short": 0.0, "no_trade": 20.0, "risk": 10.0}
    evidence = {"long": 0, "short": 0}
    reasons: list[str] = []

    if primary is None:
        return SignalScore(
            long_score=0.0,
            short_score=0.0,
            no_trade_score=85.0,
            risk_score=35.0,
            reasons=["기술적 분석 데이터 없음 — 차트 시그널 보류"],
        )

    rsi = float(getattr(primary, "rsi", 50.0) or 50.0)
    macd = getattr(primary, "macd", None)
    ema = getattr(primary, "ema", None)
    bb = getattr(primary, "bollinger_bands", None)
    volume_ratio = float(getattr(primary, "volume_ratio", 1.0) or 1.0)
    timeframe = getattr(primary, "timeframe", "primary")

    support_levels = list(getattr(technical_result, "support_levels", []) or [])
    resistance_levels = list(getattr(technical_result, "resistance_levels", []) or [])
    near_support, support = _near_level(price, support_levels, near_level_pct)
    near_resistance, resistance = _near_level(price, resistance_levels, near_level_pct)

    # 공통 지표 해석.
    if rsi <= 35:
        _add(scores, evidence, "long", 12.0, f"RSI {rsi:.1f}: 과매도/풀백 구간", reasons)
    elif rsi >= 65:
        _add(scores, evidence, "short", 12.0, f"RSI {rsi:.1f}: 과매수/반락 경계", reasons)
    elif 45 <= rsi <= 55:
        scores["no_trade"] += 5.0
        reasons.append(f"RSI {rsi:.1f}: 중립 구간")

    if macd is not None:
        hist = float(getattr(macd, "histogram", 0.0) or 0.0)
        cross = str(getattr(macd, "cross", "neutral") or "neutral")
        if cross == "bullish" or hist > 0:
            points = 12.0 if cross == "bullish" else 8.0
            _add(scores, evidence, "long", points, "MACD 상승 모멘텀", reasons)
        if cross == "bearish" or hist < 0:
            points = 12.0 if cross == "bearish" else 8.0
            _add(scores, evidence, "short", points, "MACD 하락 모멘텀", reasons)

    ema_alignment = str(getattr(ema, "alignment", "mixed") if ema is not None else "mixed")
    if ema_alignment == "bullish":
        _add(scores, evidence, "long", 14.0, f"EMA 정배열 ({timeframe})", reasons)
    elif ema_alignment == "bearish":
        _add(scores, evidence, "short", 14.0, f"EMA 역배열 ({timeframe})", reasons)
    else:
        scores["no_trade"] += 6.0
        reasons.append(f"EMA 혼조 ({timeframe})")

    if bb is not None:
        pct_b = float(getattr(bb, "percent_b", 0.5) or 0.5)
        if pct_b <= 0.25:
            reason = f"BB %B {pct_b:.2f}: 하단 밴드 근접"
            _add(scores, evidence, "long", 10.0, reason, reasons)
        elif pct_b >= 0.75:
            reason = f"BB %B {pct_b:.2f}: 상단 밴드 근접"
            _add(scores, evidence, "short", 10.0, reason, reasons)
        else:
            scores["no_trade"] += 4.0
            reasons.append(f"BB %B {pct_b:.2f}: 중앙권")

    if near_support:
        reason = f"현재가가 지지선 {support:.2f} 근처"
        _add(scores, evidence, "long", 10.0, reason, reasons)
    if near_resistance:
        reason = f"현재가가 저항선 {resistance:.2f} 근처"
        _add(scores, evidence, "short", 10.0, reason, reasons)

    if volume_ratio >= volume_spike_ratio:
        scores["risk"] += 8.0
        if price_change > 0:
            reason = f"거래량 {volume_ratio:.1f}x + 최근 가격 상승"
            _add(scores, evidence, "long", 8.0, reason, reasons)
        elif price_change < 0:
            reason = f"거래량 {volume_ratio:.1f}x + 최근 가격 하락"
            _add(scores, evidence, "short", 8.0, reason, reasons)
        else:
            scores["no_trade"] += 6.0
            reasons.append(f"거래량 {volume_ratio:.1f}x이나 가격 방향 확인 부족")
    elif volume_ratio < 0.8:
        scores["no_trade"] += 6.0
        reasons.append(f"거래량 {volume_ratio:.1f}x: 확인 거래량 부족")

    # 시장 국면별 가중치.
    if regime == MarketRegime.TREND_UP:
        has_pullback = (
            rsi <= 45
            or near_support
            or (bb is not None and getattr(bb, "percent_b", 0.5) <= 0.45)
        )
        if ema_alignment == "bullish" and has_pullback:
            scores["long"] += 18.0
            reasons.append("TREND_UP: 상승 추세 내 풀백 롱 셋업 우대")
        scores["short"] *= 0.65
        scores["no_trade"] += 8.0 if evidence["long"] < 2 else 0.0
    elif regime == MarketRegime.TREND_DOWN:
        has_bounce = (
            rsi >= 55
            or near_resistance
            or (bb is not None and getattr(bb, "percent_b", 0.5) >= 0.55)
        )
        if ema_alignment == "bearish" and has_bounce:
            scores["short"] += 18.0
            reasons.append("TREND_DOWN: 하락 추세 내 숏 셋업 우대")
        scores["long"] *= 0.55
        scores["no_trade"] += 14.0 if evidence["short"] < 2 else 4.0
    elif regime == MarketRegime.RANGE:
        if near_support or rsi <= 35 or (bb and getattr(bb, "percent_b", 0.5) <= 0.25):
            scores["long"] += 12.0
            reasons.append("RANGE: 하단/지지선 평균회귀 롱 허용")
        if near_resistance or rsi >= 65 or (bb and getattr(bb, "percent_b", 0.5) >= 0.75):
            scores["short"] += 12.0
            reasons.append("RANGE: 상단/저항선 평균회귀 숏 허용")
        if evidence["long"] == 0 and evidence["short"] == 0:
            scores["no_trade"] += 18.0
            reasons.append("RANGE: 평균회귀 극단값 없음")
    elif regime == MarketRegime.HIGH_VOLATILITY:
        scores["no_trade"] += 35.0
        scores["risk"] += 35.0
        scores["long"] *= 0.70
        scores["short"] *= 0.70
        reasons.append("HIGH_VOLATILITY: 신규 진입 보수 처리")
    elif regime == MarketRegime.NEWS_EVENT:
        scores["no_trade"] += 45.0
        scores["risk"] += 40.0
        scores["long"] *= 0.60
        scores["short"] *= 0.60
        reasons.append("NEWS_EVENT: 뉴스 이벤트 구간 리스크 확대")
    else:
        scores["no_trade"] += 25.0
        scores["risk"] += 12.0
        reasons.append("UNKNOWN: 시장 국면 합의 부족")

    # 단일 지표 거래 방지 및 충돌 처리.
    if evidence["long"] == 1:
        scores["long"] *= 0.55
        scores["no_trade"] += 12.0
        reasons.append("롱 근거가 단일 지표에 가까워 점수 축소")
    if evidence["short"] == 1:
        scores["short"] *= 0.55
        scores["no_trade"] += 12.0
        reasons.append("숏 근거가 단일 지표에 가까워 점수 축소")

    if evidence["long"] >= 2 and evidence["short"] >= 2:
        scores["no_trade"] += conflict_penalty
        scores["risk"] += 8.0
        reasons.append("롱/숏 지표가 동시에 다수 발생 - 충돌로 관망 점수 증가")

    return SignalScore(
        long_score=round(_clamp(scores["long"]), 2),
        short_score=round(_clamp(scores["short"]), 2),
        no_trade_score=round(_clamp(scores["no_trade"]), 2),
        risk_score=round(_clamp(scores["risk"]), 2),
        reasons=reasons,
    )
