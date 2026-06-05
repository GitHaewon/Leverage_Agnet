"""
RSI Reversal Strategy.

조건:
  LONG  — RSI ≤ 35, BB %B ≤ 0.25 (하단 밴드 근접)
  SHORT — RSI ≥ 65, BB %B ≥ 0.75 (상단 밴드 근접)

SL/TP:
  sl_distance = 1.0 × ATR
  TP: BB 중심선(middle)이 2.5×ATR 보다 멀면 BB 중심선 사용,
      아니면 2.5×ATR (최소 R:R 2.5 보장)
"""
from __future__ import annotations

import logging

from agents.strategy.base import BaseStrategy, TARGET_RR, _build_signal, _no_trade
from agents.strategy.models import StrategyInput, StrategySignal

logger = logging.getLogger(__name__)

_MIN_ATR = 1.0
_SL_ATR_MULT = 1.0      # SL = 1 × ATR

# RSI 임계값
_RSI_OVERSOLD_STRONG  = 25
_RSI_OVERSOLD         = 30
_RSI_OVERSOLD_WEAK    = 35
_RSI_OVERBOUGHT_WEAK  = 65
_RSI_OVERBOUGHT       = 70
_RSI_OVERBOUGHT_STRONG = 75

# BB %B 임계값
_BB_LOWER_STRONG = 0.10
_BB_LOWER        = 0.25
_BB_UPPER        = 0.75
_BB_UPPER_STRONG = 0.90


class RSIReversalStrategy(BaseStrategy):
    """RSI 과매수/과매도 역발상 전략."""

    name = "rsi_reversal"

    def __init__(self, timeframe: str = "1h") -> None:
        self._tf = timeframe

    def evaluate(self, inp: StrategyInput) -> StrategySignal:
        tf_data = inp.ta_result.analyses.get(self._tf)
        if tf_data is None:
            return _no_trade(self.name, inp.current_price, f"{self._tf} 타임프레임 데이터 없음")

        rsi = tf_data.rsi
        bb = tf_data.bollinger_bands
        macd = tf_data.macd
        atr = max(tf_data.atr, _MIN_ATR)
        price = float(inp.current_price)
        signals: list[str] = []

        long_rsi_ok  = rsi <= _RSI_OVERSOLD_WEAK
        short_rsi_ok = rsi >= _RSI_OVERBOUGHT_WEAK
        long_bb_ok   = bb.percent_b <= _BB_LOWER
        short_bb_ok  = bb.percent_b >= _BB_UPPER

        if long_rsi_ok and long_bb_ok:
            direction = "LONG"
        elif short_rsi_ok and short_bb_ok:
            direction = "SHORT"
        else:
            return _no_trade(
                self.name, inp.current_price,
                f"RSI={rsi:.1f} / BB %B={bb.percent_b:.2f} — 반전 조건 미충족"
            )

        # ── 신뢰도 계산 ──────────────────────────────────────────────────────
        confidence = _base_confidence(rsi, bb.percent_b, direction)
        signals.append(f"rsi_{direction.lower()}_{self._tf}")

        # BB 강한 확인
        if (direction == "LONG" and bb.percent_b <= _BB_LOWER_STRONG) or (
            direction == "SHORT" and bb.percent_b >= _BB_UPPER_STRONG
        ):
            confidence += 0.05
            signals.append(f"bb_extreme_{direction.lower()}_{self._tf}")

        # MACD 크로스 확인
        if (direction == "LONG" and macd.cross == "bullish") or (
            direction == "SHORT" and macd.cross == "bearish"
        ):
            confidence += 0.08
            signals.append(f"macd_{macd.cross}_cross_{self._tf}")
        elif (direction == "LONG" and macd.histogram > 0) or (
            direction == "SHORT" and macd.histogram < 0
        ):
            confidence += 0.03

        # ── TP/SL 계산 ───────────────────────────────────────────────────────
        sl_distance = _SL_ATR_MULT * atr
        min_tp_distance = sl_distance * TARGET_RR

        if direction == "LONG":
            bb_tp_distance = bb.middle - price
            tp_distance = max(bb_tp_distance, min_tp_distance)
        else:
            bb_tp_distance = price - bb.middle
            tp_distance = max(bb_tp_distance, min_tp_distance)

        # tp_distance가 결정되면 실제 R:R 재계산
        actual_rr = tp_distance / sl_distance if sl_distance > 0 else TARGET_RR

        reason = (
            f"RSI={rsi:.1f} ({'과매도' if direction == 'LONG' else '과매수'}), "
            f"BB %B={bb.percent_b:.2f}, "
            f"MACD 히스토그램={macd.histogram:.1f}, ATR={atr:.1f}"
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


def _base_confidence(rsi: float, pct_b: float, direction: str) -> float:
    """RSI 깊이에 따른 기본 신뢰도."""
    if direction == "LONG":
        if rsi <= _RSI_OVERSOLD_STRONG:
            return 0.78
        if rsi <= _RSI_OVERSOLD:
            return 0.68
        return 0.58   # ≤ 35
    else:
        if rsi >= _RSI_OVERBOUGHT_STRONG:
            return 0.78
        if rsi >= _RSI_OVERBOUGHT:
            return 0.68
        return 0.58   # ≥ 65
