"""
Strategy type selector — 결정적 전략 유형 선택.

규칙:
  - AI 호출 없음. 주문 없음. 순수 분류 함수.
  - HIGH_VOLATILITY / NEWS_EVENT 국면에서는 모든 전략 차단 → UNKNOWN.
  - news_score.no_trade_flag=True 이면 전략 선택 불가 → UNKNOWN.
  - 선택 우선순위: TREND_FOLLOWING → BREAKOUT → INTRADAY → SCALPING → UNKNOWN.
  - UNKNOWN은 상위 레이어에서 반드시 HOLD로 처리해야 한다.
"""
from __future__ import annotations

from typing import Any

from agents.decision.constants import (
    REGIME_ALLOWED_STRATEGIES,
    STRATEGY_HOLDING_MINUTES,
    STRATEGY_MAX_BREAKOUT_PRICE_MOVE,
    STRATEGY_MAX_RISK_FOR_BREAKOUT,
    STRATEGY_MAX_RISK_FOR_INTRADAY,
    STRATEGY_MAX_RISK_FOR_SCALPING,
    STRATEGY_MAX_RISK_FOR_TREND,
    STRATEGY_MIN_BREAKOUT_VOL_RATIO,
    STRATEGY_MIN_INTRADAY_DIR_SCORE,
    STRATEGY_MIN_SCALPING_DIR_SCORE,
    STRATEGY_MIN_TREND_DIR_SCORE,
    STRATEGY_THRESHOLDS,
)
from agents.decision.models import (
    MarketRegime,
    MarketRegimeResult,
    StrategySelectionResult,
    StrategyType,
)


# ── 유틸리티 ─────────────────────────────────────────────────────────────────

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _cfg(config: dict | None, key: str, default: Any) -> Any:
    return config.get(key, default) if config else default


def _as_regime(market_regime: Any) -> MarketRegime:
    if isinstance(market_regime, MarketRegimeResult):
        return market_regime.regime
    if isinstance(market_regime, MarketRegime):
        return market_regime
    if market_regime is None:
        return MarketRegime.UNKNOWN
    try:
        return MarketRegime(str(market_regime))
    except ValueError:
        return MarketRegime.UNKNOWN


def _get_float(obj: Any, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if obj is None:
            break
        val = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return default


def _combined_risk(chart_score: Any, news_score: Any, derivatives_score: Any) -> float:
    """통합 리스크 = chart*0.4 + news*0.3 + deriv*0.3 (0~100 클램프)."""
    chart_risk = _get_float(chart_score,       "risk_score", default=50.0)
    news_risk  = _get_float(news_score,        "risk_score", default=0.0)
    deriv_risk = _get_float(derivatives_score, "risk_score", default=0.0)
    raw = chart_risk * 0.4 + news_risk * 0.3 + deriv_risk * 0.3
    return round(_clamp(raw, 0.0, 100.0), 2)


def _max_dir_score(chart_score: Any) -> float:
    long_s  = _get_float(chart_score, "long_score")
    short_s = _get_float(chart_score, "short_score")
    return max(long_s, short_s)


def _direction_label(chart_score: Any) -> str:
    long_s  = _get_float(chart_score, "long_score")
    short_s = _get_float(chart_score, "short_score")
    if long_s > short_s:
        return "LONG"
    if short_s > long_s:
        return "SHORT"
    return "NEUTRAL"


def _crowded_side(derivatives_score: Any) -> str:
    val = (
        derivatives_score.get("crowded_side")
        if isinstance(derivatives_score, dict)
        else getattr(derivatives_score, "crowded_side", "NONE")
    )
    return str(val) if val is not None else "NONE"


def _spread_bps(market_data: dict | None) -> float:
    return _get_float(market_data, "spread_bps", "spread", default=0.0)


def _volume_ratio(market_data: dict | None) -> float:
    if not market_data:
        return 1.0
    for key in ("volume_ratio", "vol_ratio", "volume_multiplier"):
        val = market_data.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 1.0


def _price_change_abs_pct(market_data: dict | None) -> float:
    return abs(_get_float(
        market_data,
        "price_change_pct",
        "recent_price_change_pct",
        "price_change_1h_pct",
        default=0.0,
    ))


def _strategy_key(strategy_name: Any) -> str:
    value = getattr(strategy_name, "strategy_type", strategy_name)
    value = getattr(value, "value", value)
    if value is None:
        return "UNKNOWN"
    key = str(value).strip().upper()
    aliases = {
        "TREND": "TREND_FOLLOWING",
        "TREND_PULLBACK_LONG": "TREND_PULLBACK",
        "TREND_PULLBACK_SHORT": "TREND_PULLBACK",
        "PULLBACK": "TREND_PULLBACK",
        "BREAKOUT_RETEST_LONG": "BREAKOUT_RETEST",
        "BREAKOUT_RETEST_SHORT": "BREAKOUT_RETEST",
        "RETEST": "BREAKOUT_RETEST",
        "RANGE_MEAN_REVERSION": "MEAN_REVERSION",
        "MEAN_REVERSION_LONG": "MEAN_REVERSION",
        "MEAN_REVERSION_SHORT": "MEAN_REVERSION",
    }
    return aliases.get(key, key)


def get_allowed_strategies_for_regime(market_regime: Any) -> tuple[str, ...]:
    """시장 국면별 허용 전략 목록을 반환한다. UNKNOWN은 보수적으로 빈 목록."""
    regime = _as_regime(market_regime)
    return REGIME_ALLOWED_STRATEGIES.get(regime.value, REGIME_ALLOWED_STRATEGIES["UNKNOWN"])


def is_strategy_allowed_for_regime(strategy_name: Any, market_regime: Any) -> bool:
    """후보 전략이 현재 시장 국면 플레이북에서 허용되는지 확인한다."""
    strategy = _strategy_key(strategy_name)
    return strategy in get_allowed_strategies_for_regime(market_regime)


# ── 결과 생성 헬퍼 ────────────────────────────────────────────────────────────

def _make_result(strategy: str, reasons: list[str]) -> StrategySelectionResult:
    th = STRATEGY_THRESHOLDS[strategy]
    return StrategySelectionResult(
        strategy_type=StrategyType(strategy),
        expected_holding_minutes=STRATEGY_HOLDING_MINUTES[strategy],
        min_required_rr=th.min_risk_reward_ratio,
        reasons=reasons,
    )


def _make_unknown(reasons: list[str]) -> StrategySelectionResult:
    return StrategySelectionResult(
        strategy_type=StrategyType.UNKNOWN,
        expected_holding_minutes=0,
        min_required_rr=0.0,
        reasons=reasons,
    )


# ── 공개 API ─────────────────────────────────────────────────────────────────

def select_strategy_type(
    market_regime: Any | None,
    chart_score: Any | None,
    news_score: Any | None,
    derivatives_score: Any | None,
    market_data: dict | None,
    config: dict | None = None,
) -> StrategySelectionResult:
    """
    시장 국면·차트·감성·파생 데이터를 종합해 최적 전략 유형을 하나 선택한다.

    선택 우선순위:
      1. TREND_FOLLOWING  (TREND_UP / TREND_DOWN + 강한 방향성)
      2. BREAKOUT         (거래량 급증 + 이른 진입 기회)
      3. INTRADAY         (보통 추세·횡보 + 적정 방향성)
      4. SCALPING         (저변동 + 타이트 스프레드 + 소폭 엣지)
      5. UNKNOWN          (조건 미충족 → 상위 레이어 HOLD 처리)

    Parameters
    ----------
    market_regime:      MarketRegime / MarketRegimeResult / str / None.
    chart_score:        SignalScore (score_chart_signals 반환값).
    news_score:         NewsSentimentScore (score_news_sentiment 반환값).
    derivatives_score:  DerivativesMarketScore (score_derivatives_market 반환값).
    market_data:        spread_bps, volume_ratio, price_change_pct 등 선택 필드.
    config:             런타임 임계값 오버라이드.
                        키 목록:
                          min_trend_dir_score      (float, 기본 55.0)
                          max_risk_trend           (float, 기본 55.0)
                          min_breakout_volume_ratio (float, 기본 1.8)
                          max_breakout_price_move  (float, 기본 3.0)
                          max_risk_breakout        (float, 기본 50.0)
                          min_intraday_dir_score   (float, 기본 35.0)
                          max_risk_intraday        (float, 기본 60.0)
                          min_scalping_dir_score   (float, 기본 20.0)
                          max_risk_scalping        (float, 기본 40.0)

    Returns
    -------
    StrategySelectionResult(strategy_type, expected_holding_minutes, min_required_rr, reasons)
    """
    regime  = _as_regime(market_regime)
    data    = market_data or {}
    reasons: list[str] = []

    # ── 임계값 (상수 기본값 + config 오버라이드) ────────────────────────────
    min_trend_dir     = float(_cfg(config, "min_trend_dir_score",       STRATEGY_MIN_TREND_DIR_SCORE))
    max_risk_trend    = float(_cfg(config, "max_risk_trend",            STRATEGY_MAX_RISK_FOR_TREND))
    min_bko_vol       = float(_cfg(config, "min_breakout_volume_ratio", STRATEGY_MIN_BREAKOUT_VOL_RATIO))
    max_bko_move      = float(_cfg(config, "max_breakout_price_move",   STRATEGY_MAX_BREAKOUT_PRICE_MOVE))
    max_risk_bko      = float(_cfg(config, "max_risk_breakout",         STRATEGY_MAX_RISK_FOR_BREAKOUT))
    min_intraday_dir  = float(_cfg(config, "min_intraday_dir_score",    STRATEGY_MIN_INTRADAY_DIR_SCORE))
    max_risk_intraday = float(_cfg(config, "max_risk_intraday",         STRATEGY_MAX_RISK_FOR_INTRADAY))
    min_scalping_dir  = float(_cfg(config, "min_scalping_dir_score",    STRATEGY_MIN_SCALPING_DIR_SCORE))
    max_risk_scalping = float(_cfg(config, "max_risk_scalping",         STRATEGY_MAX_RISK_FOR_SCALPING))

    # ── 파생 지표 계산 ────────────────────────────────────────────────────────
    combined_risk = _combined_risk(chart_score, news_score, derivatives_score)
    max_dir       = _max_dir_score(chart_score)
    direction     = _direction_label(chart_score)
    crowded       = _crowded_side(derivatives_score)
    spread        = _spread_bps(data)
    vol_ratio     = _volume_ratio(data)
    price_move    = _price_change_abs_pct(data)
    no_trade_flag = bool(getattr(news_score, "no_trade_flag", False)) if news_score is not None else False

    reasons.append(
        f"국면={regime.value}, 방향={direction}, "
        f"방향점수={max_dir:.1f}, 통합리스크={combined_risk:.1f}, "
        f"거래량배율={vol_ratio:.2f}x, 스프레드={spread:.1f}bps"
    )

    # ── 전역 차단 조건 ────────────────────────────────────────────────────────
    if regime == MarketRegime.HIGH_VOLATILITY:
        reasons.append("HIGH_VOLATILITY — 모든 진입 전략 차단 → UNKNOWN")
        return _make_unknown(reasons)

    if regime == MarketRegime.NEWS_EVENT:
        reasons.append("NEWS_EVENT — 모든 진입 전략 차단 → UNKNOWN")
        return _make_unknown(reasons)

    if no_trade_flag:
        reasons.append("no_trade_flag=True (뉴스 이벤트·극단 시황) — 전략 선택 불가 → UNKNOWN")
        return _make_unknown(reasons)

    if chart_score is None:
        reasons.append("차트 점수 없음 — 전략 선택 불가 → UNKNOWN")
        return _make_unknown(reasons)

    # ── 1순위: TREND_FOLLOWING ───────────────────────────────────────────────
    if regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
        effective_risk = combined_risk
        if crowded == direction and direction != "NEUTRAL":
            effective_risk = min(100.0, combined_risk + 10.0)
            reasons.append(
                f"추세 방향({direction})에 포지션 쏠림 감지 — "
                f"유효 리스크 {combined_risk:.1f} → {effective_risk:.1f}"
            )
        if max_dir >= min_trend_dir and effective_risk <= max_risk_trend:
            reasons.append(
                f"{regime.value}: 방향점수({max_dir:.1f}>={min_trend_dir:.0f}) "
                f"+ 리스크({effective_risk:.1f}<={max_risk_trend:.0f}) → TREND_FOLLOWING"
            )
            return _make_result("TREND_FOLLOWING", reasons)
        reasons.append(
            f"TREND_FOLLOWING 스킵: 방향점수({max_dir:.1f}<{min_trend_dir}) "
            f"또는 리스크({effective_risk:.1f}>{max_risk_trend})"
        )

    # ── 2순위: BREAKOUT ───────────────────────────────────────────────────────
    if vol_ratio >= min_bko_vol:
        if price_move >= max_bko_move:
            reasons.append(
                f"BREAKOUT 스킵: 거래량({vol_ratio:.1f}x)이나 "
                f"가격 이미 이동({price_move:.1f}%>={max_bko_move:.1f}%) — 기회 소멸"
            )
        elif crowded == direction and direction != "NEUTRAL":
            # 브레이크아웃 방향과 동일한 쪽이 혼잡 → 손절 위험
            reasons.append(
                f"BREAKOUT 거부: 거래량({vol_ratio:.1f}x)이나 "
                f"{direction} 방향 포지션 혼잡 → UNKNOWN"
            )
            return _make_unknown(reasons)
        elif combined_risk <= max_risk_bko:
            reasons.append(
                f"거래량({vol_ratio:.1f}x) + 가격이동({price_move:.1f}%) "
                f"+ 리스크({combined_risk:.1f}<={max_risk_bko:.0f}) → BREAKOUT"
            )
            return _make_result("BREAKOUT", reasons)
        else:
            reasons.append(
                f"BREAKOUT 스킵: 거래량({vol_ratio:.1f}x)이나 "
                f"리스크 초과({combined_risk:.1f}>{max_risk_bko:.0f})"
            )

    # ── 3순위: INTRADAY ───────────────────────────────────────────────────────
    if regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN, MarketRegime.RANGE):
        max_intraday_spread = STRATEGY_THRESHOLDS["INTRADAY"].max_spread_bps
        if spread > max_intraday_spread:
            reasons.append(
                f"INTRADAY 스킵: 스프레드({spread:.1f}>{max_intraday_spread}bps)"
            )
        elif max_dir >= min_intraday_dir and combined_risk <= max_risk_intraday:
            reasons.append(
                f"방향점수({max_dir:.1f}>={min_intraday_dir:.0f}) "
                f"+ 리스크({combined_risk:.1f}<={max_risk_intraday:.0f}) → INTRADAY"
            )
            return _make_result("INTRADAY", reasons)
        else:
            reasons.append(
                f"INTRADAY 스킵: 방향점수({max_dir:.1f}<{min_intraday_dir}) "
                f"또는 리스크({combined_risk:.1f}>{max_risk_intraday})"
            )

    # ── 4순위: SCALPING ───────────────────────────────────────────────────────
    max_scalping_spread = STRATEGY_THRESHOLDS["SCALPING"].max_spread_bps
    if spread > max_scalping_spread:
        reasons.append(
            f"SCALPING 차단: 스프레드({spread:.1f}>{max_scalping_spread}bps)"
        )
    elif max_dir >= min_scalping_dir and combined_risk <= max_risk_scalping:
        reasons.append(
            f"소폭 방향 엣지({max_dir:.1f}>={min_scalping_dir:.0f}) "
            f"+ 타이트 스프레드({spread:.1f}bps) + 리스크({combined_risk:.1f}) → SCALPING"
        )
        return _make_result("SCALPING", reasons)
    else:
        reasons.append(
            f"SCALPING 스킵: 방향점수({max_dir:.1f}<{min_scalping_dir}) "
            f"또는 리스크({combined_risk:.1f}>{max_risk_scalping})"
        )

    reasons.append("전략 선택 조건 미충족 → UNKNOWN")
    return _make_unknown(reasons)
