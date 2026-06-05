"""
Kelly Criterion 구현.

수식:
  f* = (p × b - q) / b

  f* = Kelly 최적 베팅 비율 (자본 대비)
  p  = 승률 (win probability)
  q  = 패율 (1 - p)
  b  = 평균 수익 / 평균 손실 (odds)

분수 Kelly (Fractional Kelly):
  실전에서 Full Kelly는 변동성이 너무 크다.
  Half-Kelly (0.5×), Quarter-Kelly (0.25×)가 일반적.
  이 시스템은 기본 Quarter-Kelly (0.25×) 사용.

Kelly < 0인 경우:
  기대값이 음수 → 거래하지 말아야 한다는 신호.
  안전을 위해 fallback_risk_pct 적용.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from agents.risk.constants import RISK_PER_TRADE_MAX, RISK_PER_TRADE_MIN
from agents.risk.sizing_models import KellyResult, TradeStatistics

logger = logging.getLogger(__name__)

# ── Kelly 계산 한계값 ────────────────────────────────────────────────────────────
_KELLY_MAX_FRACTION = 1.0        # Raw Kelly 100% 상한 (이 이상은 의미 없음)
_MIN_WIN_RATE       = 0.01       # 1% 미만 승률은 계산 불가
_MIN_AVG_ODDS       = 0.01       # 평균 odds 0.01 미만은 계산 불가


def calculate_kelly(
    stats: TradeStatistics,
    kelly_fraction: float = 0.25,
    min_sample_size: int = 20,
    fallback_risk_pct: float = 0.01,
) -> KellyResult:
    """
    Kelly Criterion 계산.

    Args:
        stats:            거래 통계 (TradeStatistics)
        kelly_fraction:   분수 Kelly 비율 (0.25 = Quarter-Kelly)
        min_sample_size:  최소 샘플 수 (미달 시 fallback 적용)
        fallback_risk_pct: 데이터 부족 또는 음수 Kelly 시 대체값

    Returns:
        KellyResult
    """
    # ── 유효성 검사 ───────────────────────────────────────────────────────────

    if stats.total_trades < min_sample_size:
        logger.info(
            "Kelly: 샘플 부족 (%d/%d) — fallback %.1f%% 적용",
            stats.total_trades, min_sample_size, fallback_risk_pct * 100,
        )
        return KellyResult(
            full_kelly_fraction=fallback_risk_pct,
            applied_fraction=fallback_risk_pct,
            kelly_multiplier=kelly_fraction,
            win_rate=stats.win_rate,
            avg_odds=stats.avg_odds,
            sample_size=stats.total_trades,
            is_valid=False,
            reason=f"샘플 부족: {stats.total_trades}/{min_sample_size} 거래",
        )

    win_rate = stats.win_rate
    avg_odds = stats.avg_odds

    if win_rate < _MIN_WIN_RATE:
        return _invalid_kelly(
            win_rate, avg_odds, stats.total_trades, kelly_fraction,
            fallback_risk_pct, "승률이 너무 낮음",
        )

    if avg_odds < _MIN_AVG_ODDS:
        return _invalid_kelly(
            win_rate, avg_odds, stats.total_trades, kelly_fraction,
            fallback_risk_pct, "평균 수익/손실 비율이 0에 가까움",
        )

    # ── Full Kelly 계산 ──────────────────────────────────────────────────────
    # f* = (p × b - q) / b = (p × b - (1-p)) / b
    loss_rate = 1.0 - win_rate
    full_kelly = (win_rate * avg_odds - loss_rate) / avg_odds

    logger.debug(
        "Kelly raw: win_rate=%.1f%% avg_odds=%.3f full_kelly=%.4f",
        win_rate * 100, avg_odds, full_kelly,
    )

    # Kelly < 0: 기대값 음수 → 거래 비권장, fallback 사용
    if full_kelly <= 0:
        logger.warning(
            "Kelly 음수 (%.4f): 기대값 < 0 — 전략 검토 필요. fallback %.1f%% 적용",
            full_kelly, fallback_risk_pct * 100,
        )
        return KellyResult(
            full_kelly_fraction=full_kelly,
            applied_fraction=fallback_risk_pct,
            kelly_multiplier=kelly_fraction,
            win_rate=win_rate,
            avg_odds=avg_odds,
            sample_size=stats.total_trades,
            is_valid=False,
            reason=f"Kelly 음수 ({full_kelly:.4f}): 기대값이 음수입니다. 전략을 검토하세요.",
        )

    # Kelly 상한 클리핑 (100% 초과는 레버리지 과용)
    full_kelly = min(full_kelly, _KELLY_MAX_FRACTION)

    # ── 분수 Kelly 적용 ──────────────────────────────────────────────────────
    applied = full_kelly * kelly_fraction

    # 절대 안전 상한 적용
    applied = max(RISK_PER_TRADE_MIN, min(RISK_PER_TRADE_MAX, applied))

    logger.info(
        "Kelly: full=%.4f × %.2f = %.4f → capped=%.4f (%.2f%%)",
        full_kelly, kelly_fraction, full_kelly * kelly_fraction, applied, applied * 100,
    )

    return KellyResult(
        full_kelly_fraction=full_kelly,
        applied_fraction=applied,
        kelly_multiplier=kelly_fraction,
        win_rate=win_rate,
        avg_odds=avg_odds,
        sample_size=stats.total_trades,
        is_valid=True,
    )


def _invalid_kelly(
    win_rate: float,
    avg_odds: float,
    sample_size: int,
    kelly_fraction: float,
    fallback: float,
    reason: str,
) -> KellyResult:
    return KellyResult(
        full_kelly_fraction=0.0,
        applied_fraction=fallback,
        kelly_multiplier=kelly_fraction,
        win_rate=win_rate,
        avg_odds=avg_odds,
        sample_size=sample_size,
        is_valid=False,
        reason=reason,
    )


def kelly_growth_rate(win_rate: float, avg_odds: float, kelly_fraction: float) -> float:
    """
    분수 Kelly 적용 시 로그 기대 성장률.
    G = p × ln(1 + f*b) + q × ln(1 - f*)
    """
    import math
    f = (win_rate * avg_odds - (1 - win_rate)) / avg_odds * kelly_fraction
    if f >= 1.0 or f <= -1.0:
        return float("-inf")
    try:
        g = win_rate * math.log(1 + f * avg_odds) + (1 - win_rate) * math.log(1 - f)
        return g
    except (ValueError, ZeroDivisionError):
        return float("-inf")


def recommended_kelly_fraction(
    sample_size: int,
    win_rate: float,
    avg_odds: float,
) -> float:
    """
    샘플 크기와 전략 안정성에 따른 분수 Kelly 추천.

    | 샘플 | 신뢰도 | 추천 Kelly |
    |------|--------|------------|
    | < 20 | 낮음   | Fallback (1%) |
    | 20~50 | 보통  | 1/8 Kelly  |
    | 50~100 | 높음 | 1/4 Kelly  |
    | > 100  | 매우높음 | 1/2 Kelly (최대) |
    """
    if sample_size < 20:
        return 0.0      # fallback 사용
    if sample_size < 50:
        return 0.125    # Eighth-Kelly
    if sample_size < 100:
        return 0.25     # Quarter-Kelly
    return 0.5          # Half-Kelly (50 이상만)
