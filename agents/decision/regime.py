"""
Market Regime Classifier — 결정적 시장 국면 분류.

규칙:
  - AI 호출 없음. 주문 없음. 순수 분류 함수.
  - 단일 지표 의존 금지 — REGIME_MIN_SIGNALS 개 이상 동시 만족해야 분류.
  - HIGH_VOLATILITY: 상위 레이어에서 리스크 증가 또는 진입 차단에 사용.
  - NEWS_EVENT: 설정에 따라 신규 진입 차단.
  - UNKNOWN: 항상 보수적 처리 (진입 차단 권장).

분류 우선순위:
  1. NEWS_EVENT      (news_event 플래그 감지 시 즉시 반환)
  2. HIGH_VOLATILITY (BB bandwidth / ATR / 거래량 스파이크 중 2개 이상)
  3. TREND_UP        (EMA 정배열 / tech_score 양수 / 전략 방향 LONG 중 2개 이상)
  4. TREND_DOWN      (EMA 역배열 / tech_score 음수 / 전략 방향 SHORT 중 2개 이상)
  5. RANGE           (EMA 혼조 / 좁은 BB / tech_score ≈ 0 / NO_TRADE 중 2개 이상)
  6. UNKNOWN         (데이터 부족 또는 합의 없음)
"""
from __future__ import annotations

from typing import Any

from agents.decision.constants import (
    ATR_HIGH_VOL_PCT,
    BB_HIGH_VOL_BANDWIDTH_PCT,
    BB_RANGE_BANDWIDTH_PCT,
    REGIME_MIN_SIGNALS,
    TECH_SCORE_RANGE_THRESHOLD,
    TECH_SCORE_TREND_THRESHOLD,
    VOLUME_SPIKE_RATIO,
)
from agents.decision.models import MarketRegime, MarketRegimeResult

# 타임프레임 우선순위: 주 분석 TF 선택 기준
_PRIMARY_TF_ORDER = ("1h", "4h", "15m", "5m", "1d")
# 확인 TF 순서: 주 TF보다 상위 TF 우선
_CONFIRM_TF_ORDER = ("4h", "1d", "1h", "15m", "5m")


# ── 타임프레임 선택 헬퍼 ──────────────────────────────────────────────────────

def _select_timeframes(technical_result: Any) -> tuple[str | None, str | None]:
    """(primary_tf, confirm_tf) 반환. 분석 데이터가 없으면 None."""
    if technical_result is None:
        return None, None
    analyses: dict = getattr(technical_result, "analyses", {}) or {}
    if not analyses:
        return None, None

    primary_tf: str | None = None
    for tf in _PRIMARY_TF_ORDER:
        if tf in analyses:
            primary_tf = tf
            break
    if primary_tf is None:
        primary_tf = next(iter(analyses))

    confirm_tf: str | None = None
    for tf in _CONFIRM_TF_ORDER:
        if tf in analyses and tf != primary_tf:
            confirm_tf = tf
            break

    return primary_tf, confirm_tf


def _get_tf(technical_result: Any, tf: str | None) -> Any | None:
    """지정 타임프레임 TimeframeAnalysis 반환. 없으면 None."""
    if technical_result is None or tf is None:
        return None
    analyses: dict = getattr(technical_result, "analyses", {}) or {}
    return analyses.get(tf)


# ── 임계값 오버라이드 헬퍼 ────────────────────────────────────────────────────

def _cfg(config: dict | None, key: str, default: float | int | bool) -> Any:
    """config dict 에서 키를 읽고 없으면 기본값(상수) 반환."""
    return config.get(key, default) if config else default


# ── 공개 API ─────────────────────────────────────────────────────────────────

def classify_market_regime(
    market_data: dict | None,
    technical_result: Any,
    strategy_signal: Any | None,
    config: dict | None = None,
) -> MarketRegimeResult:
    """
    시장 국면을 결정적으로 분류한다.

    Parameters
    ----------
    market_data:      MarketDataAgent.get_snapshot() 반환 dict.
                      current_price, news_event 키를 사용.
    technical_result: TechnicalAnalysisResult (또는 None).
                      EMA, ATR, BB, volume_ratio, tech_score 를 사용.
    strategy_signal:  AggregatedSignal (또는 None).
                      direction 필드(LONG/SHORT/NO_TRADE) 를 사용.
    config:           런타임 임계값 오버라이드 dict (선택).
                      키: "bb_high_vol_bw", "atr_high_vol_pct", "volume_spike_ratio",
                          "bb_range_bw", "tech_trend_th", "tech_range_th", "min_signals"

    Returns
    -------
    MarketRegimeResult (regime + confidence + reasons)
    """
    _data = market_data or {}

    # ── 공통 데이터 추출 ─────────────────────────────────────────────────────
    current_price: float = float(_data.get("current_price", 0.0))
    news_event: bool     = bool(_data.get("news_event", False))
    tech_score: float    = float(getattr(technical_result, "tech_score", 0.0) or 0.0)
    strategy_dir: str    = str(getattr(strategy_signal, "direction", "NO_TRADE") or "NO_TRADE")

    primary_tf, confirm_tf = _select_timeframes(technical_result)
    primary = _get_tf(technical_result, primary_tf)
    confirm = _get_tf(technical_result, confirm_tf)

    # ── 임계값 (constants 기본값 + config 오버라이드) ─────────────────────────
    bb_high_vol_bw   = _cfg(config, "bb_high_vol_bw",     BB_HIGH_VOL_BANDWIDTH_PCT)
    atr_high_vol_pct = _cfg(config, "atr_high_vol_pct",   ATR_HIGH_VOL_PCT)
    vol_spike_ratio  = _cfg(config, "volume_spike_ratio",  VOLUME_SPIKE_RATIO)
    bb_range_bw      = _cfg(config, "bb_range_bw",         BB_RANGE_BANDWIDTH_PCT)
    tech_trend_th    = _cfg(config, "tech_trend_th",        TECH_SCORE_TREND_THRESHOLD)
    tech_range_th    = _cfg(config, "tech_range_th",        TECH_SCORE_RANGE_THRESHOLD)
    min_signals      = int(_cfg(config, "min_signals",      REGIME_MIN_SIGNALS))

    # ── 1순위: NEWS_EVENT ─────────────────────────────────────────────────────
    if news_event:
        return MarketRegimeResult(
            regime=MarketRegime.NEWS_EVENT,
            confidence=1.0,
            reasons=["news_event 플래그 감지 — 신규 진입 차단"],
        )

    # ── 2순위: HIGH_VOLATILITY ────────────────────────────────────────────────
    hv: list[str] = []
    if primary is not None:
        bb_bw: float = primary.bollinger_bands.bandwidth
        if bb_bw > bb_high_vol_bw:
            hv.append(
                f"BB bandwidth {bb_bw:.1f}% > 임계값 {bb_high_vol_bw:.0f}% "
                f"(타임프레임: {primary_tf})"
            )

        if current_price > 0:
            atr_pct: float = primary.atr / current_price * 100
            if atr_pct > atr_high_vol_pct:
                hv.append(
                    f"ATR {atr_pct:.2f}% > 임계값 {atr_high_vol_pct:.1f}% "
                    f"(타임프레임: {primary_tf})"
                )

        vol_ratio: float = primary.volume_ratio
        if vol_ratio > vol_spike_ratio:
            hv.append(
                f"거래량 {vol_ratio:.1f}x > 임계값 {vol_spike_ratio:.1f}x "
                f"(타임프레임: {primary_tf})"
            )

    if len(hv) >= min_signals:
        return MarketRegimeResult(
            regime=MarketRegime.HIGH_VOLATILITY,
            confidence=round(min(1.0, len(hv) / 3), 3),
            reasons=hv,
        )

    # ── 3순위: TREND_UP ───────────────────────────────────────────────────────
    up: list[str] = []
    if primary is not None and primary.ema.alignment == "bullish":
        up.append(f"EMA 정배열 (타임프레임: {primary_tf})")
    if confirm is not None and confirm.ema.alignment == "bullish":
        up.append(f"EMA 정배열 확인 (타임프레임: {confirm_tf})")
    if tech_score > tech_trend_th:
        up.append(f"tech_score {tech_score:+.2f} > +{tech_trend_th:.2f}")
    if strategy_dir == "LONG":
        up.append("전략 방향 LONG")

    if len(up) >= min_signals:
        return MarketRegimeResult(
            regime=MarketRegime.TREND_UP,
            confidence=round(min(1.0, len(up) / 4), 3),
            reasons=up,
        )

    # ── 4순위: TREND_DOWN ─────────────────────────────────────────────────────
    dn: list[str] = []
    if primary is not None and primary.ema.alignment == "bearish":
        dn.append(f"EMA 역배열 (타임프레임: {primary_tf})")
    if confirm is not None and confirm.ema.alignment == "bearish":
        dn.append(f"EMA 역배열 확인 (타임프레임: {confirm_tf})")
    if tech_score < -tech_trend_th:
        dn.append(f"tech_score {tech_score:+.2f} < -{tech_trend_th:.2f}")
    if strategy_dir == "SHORT":
        dn.append("전략 방향 SHORT")

    if len(dn) >= min_signals:
        return MarketRegimeResult(
            regime=MarketRegime.TREND_DOWN,
            confidence=round(min(1.0, len(dn) / 4), 3),
            reasons=dn,
        )

    # ── 5순위: RANGE ──────────────────────────────────────────────────────────
    rng: list[str] = []
    if primary is not None and primary.ema.alignment == "mixed":
        rng.append(f"EMA 혼조 (mixed, 타임프레임: {primary_tf})")
    if primary is not None and primary.bollinger_bands.bandwidth < bb_range_bw:
        rng.append(
            f"BB bandwidth {primary.bollinger_bands.bandwidth:.1f}% "
            f"< 임계값 {bb_range_bw:.0f}% (횡보 압축)"
        )
    # tech_score 기본값 0.0 은 "데이터 없음"을 의미할 수 있으므로 실제 결과가 있을 때만 신호로 인정
    if technical_result is not None and abs(tech_score) < tech_range_th:
        rng.append(f"tech_score {tech_score:+.2f} ≈ 0 (방향성 없음)")
    # strategy 기본값 "NO_TRADE" 는 "신호 없음"을 의미할 수 있으므로 실제 결과가 있을 때만 인정
    if strategy_signal is not None and strategy_dir == "NO_TRADE":
        rng.append("전략 방향 없음 (NO_TRADE)")

    if len(rng) >= min_signals:
        return MarketRegimeResult(
            regime=MarketRegime.RANGE,
            confidence=round(min(1.0, len(rng) / 4), 3),
            reasons=rng,
        )

    # ── 6순위: UNKNOWN ────────────────────────────────────────────────────────
    partial: list[str] = (hv + up + dn + rng)[:2]
    return MarketRegimeResult(
        regime=MarketRegime.UNKNOWN,
        confidence=0.0,
        reasons=["데이터 부족 또는 지표 합의 없음 — 보수적 처리"] + partial,
    )
