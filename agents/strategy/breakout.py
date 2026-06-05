"""
Breakout Strategy.

조건:
  LONG  — 현재가가 저항선을 막 돌파 (저항선보다 0~2% 위),
           거래량 비율 > 1.5 (돌파 확인)
  SHORT — 현재가가 지지선을 막 하향돌파 (지지선보다 0~2% 아래),
           거래량 비율 > 1.5

SL/TP:
  LONG:  SL = 돌파한 저항선 - 0.3% (저항→지지 전환)
         TP = 다음 저항선 or entry + 2.5×sl_distance
  SHORT: SL = 돌파한 지지선 + 0.3%
         TP = 다음 지지선 or entry - 2.5×sl_distance

최소 sl_distance = 0.5 × ATR (너무 좁은 SL 방지)
"""
from __future__ import annotations

import logging

from agents.strategy.base import BaseStrategy, TARGET_RR, _build_signal, _no_trade
from agents.strategy.models import StrategyInput, StrategySignal

logger = logging.getLogger(__name__)

_MIN_ATR = 1.0
_BREAKOUT_WINDOW = 0.02    # 돌파 판정 범위: 0~2% 이내
_SL_BUFFER_PCT   = 0.003   # 돌파 레벨 대비 SL 버퍼 0.3%
_MIN_SL_ATR_MULT = 0.5     # 최소 SL = 0.5 × ATR
_VOLUME_THRESHOLD = 1.5    # 최소 거래량 비율


class BreakoutStrategy(BaseStrategy):
    """지지/저항 돌파 전략."""

    name = "breakout"

    def __init__(self, timeframe: str = "1h") -> None:
        self._tf = timeframe

    def evaluate(self, inp: StrategyInput) -> StrategySignal:
        tf_data = inp.ta_result.analyses.get(self._tf)
        if tf_data is None:
            return _no_trade(self.name, inp.current_price, f"{self._tf} 타임프레임 데이터 없음")

        if tf_data.volume_ratio < _VOLUME_THRESHOLD:
            return _no_trade(
                self.name, inp.current_price,
                f"거래량 부족 (ratio={tf_data.volume_ratio:.2f} < {_VOLUME_THRESHOLD})"
            )

        price = float(inp.current_price)
        resistance_levels = inp.ta_result.resistance_levels
        support_levels    = inp.ta_result.support_levels
        atr = max(tf_data.atr, _MIN_ATR)
        signals: list[str] = []

        # ── LONG 돌파 탐지 ────────────────────────────────────────────────────
        # price가 저항선보다 0~2% 위: 막 돌파한 상태
        broken_resistance = _find_broken_level_below(price, resistance_levels, _BREAKOUT_WINDOW)

        # ── SHORT 돌파 탐지 ───────────────────────────────────────────────────
        broken_support = _find_broken_level_above(price, support_levels, _BREAKOUT_WINDOW)

        if broken_resistance and not broken_support:
            direction = "LONG"
            broken_level = broken_resistance
        elif broken_support and not broken_resistance:
            direction = "SHORT"
            broken_level = broken_support
        elif broken_resistance and broken_support:
            # 양방향 신호 충돌 → 더 가까운 레벨 선택
            long_dist = price - broken_resistance
            short_dist = broken_support - price
            if long_dist <= short_dist:
                direction = "LONG"
                broken_level = broken_resistance
            else:
                direction = "SHORT"
                broken_level = broken_support
        else:
            return _no_trade(self.name, inp.current_price, "돌파 레벨 없음")

        signals.append(f"{'resistance' if direction == 'LONG' else 'support'}_breakout_{self._tf}")

        # ── SL 계산 ──────────────────────────────────────────────────────────
        if direction == "LONG":
            raw_sl_distance = price - (broken_level * (1 - _SL_BUFFER_PCT))
        else:
            raw_sl_distance = (broken_level * (1 + _SL_BUFFER_PCT)) - price

        sl_distance = max(raw_sl_distance, _MIN_SL_ATR_MULT * atr)

        # ── TP 계산 ───────────────────────────────────────────────────────────
        min_tp_distance = sl_distance * TARGET_RR

        if direction == "LONG":
            next_level = _find_next_level_above(price, resistance_levels)
            ideal_tp_distance = (next_level - price) if next_level else 0.0
        else:
            next_level = _find_next_level_below(price, support_levels)
            ideal_tp_distance = (price - next_level) if next_level else 0.0

        tp_distance = max(ideal_tp_distance, min_tp_distance)
        actual_rr   = tp_distance / sl_distance

        # ── 신뢰도 계산 ──────────────────────────────────────────────────────
        confidence = _breakout_confidence(
            tf_data.volume_ratio,
            inp.ta_result.tech_score,
            tf_data.ema.alignment,
            direction,
        )
        if tf_data.volume_ratio >= 2.0:
            signals.append(f"volume_strong_{self._tf}")

        reason = (
            f"{'저항' if direction == 'LONG' else '지지'}선 {broken_level:.0f} 돌파, "
            f"거래량 비율={tf_data.volume_ratio:.2f}, ATR={atr:.1f}"
        )

        return _build_signal(
            strategy_name=self.name,
            direction=direction,
            confidence=confidence,
            entry=price,
            sl_distance=sl_distance,
            rr=actual_rr,
            signals_fired=signals,
            reason=reason,
        )


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _find_broken_level_below(
    price: float, levels: list[float], window: float
) -> float | None:
    """price보다 낮으면서 price × (1-window) 이상인 레벨 중 최대값."""
    candidates = [
        lv for lv in levels
        if price * (1 - window) <= lv < price
    ]
    return max(candidates) if candidates else None


def _find_broken_level_above(
    price: float, levels: list[float], window: float
) -> float | None:
    """price보다 높으면서 price × (1+window) 이하인 레벨 중 최솟값."""
    candidates = [
        lv for lv in levels
        if price < lv <= price * (1 + window)
    ]
    return min(candidates) if candidates else None


def _find_next_level_above(price: float, levels: list[float]) -> float | None:
    """price보다 높은 레벨 중 최솟값 (다음 저항선)."""
    candidates = [lv for lv in levels if lv > price]
    return min(candidates) if candidates else None


def _find_next_level_below(price: float, levels: list[float]) -> float | None:
    """price보다 낮은 레벨 중 최댓값 (다음 지지선)."""
    candidates = [lv for lv in levels if lv < price]
    return max(candidates) if candidates else None


def _breakout_confidence(
    volume_ratio: float,
    tech_score: float,
    ema_alignment: str,
    direction: str,
) -> float:
    confidence = 0.60

    if volume_ratio >= 2.5:
        confidence += 0.10
    elif volume_ratio >= 2.0:
        confidence += 0.06
    elif volume_ratio >= 1.5:
        confidence += 0.02

    # 기술 점수 방향 확인
    if direction == "LONG" and tech_score >= 0.30:
        confidence += 0.05
    elif direction == "SHORT" and tech_score <= -0.30:
        confidence += 0.05

    # EMA 추세 방향 확인
    if (direction == "LONG" and ema_alignment == "bullish") or (
        direction == "SHORT" and ema_alignment == "bearish"
    ):
        confidence += 0.05

    return min(confidence, 1.0)
