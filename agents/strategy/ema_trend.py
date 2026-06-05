"""
EMA Trend Following Strategy.

조건:
  LONG  — EMA9 > EMA21 > EMA50, 현재가 > EMA50, MACD 히스토그램 > 0
  SHORT — EMA9 < EMA21 < EMA50, 현재가 < EMA50, MACD 히스토그램 < 0

SL/TP:
  sl_distance = 1.5 × ATR
  TP = entry ± sl_distance × 2.5  (R:R 2.5)
"""
from __future__ import annotations

import logging

from agents.strategy.base import BaseStrategy, TARGET_RR, _build_signal, _no_trade
from agents.strategy.models import StrategyInput, StrategySignal

logger = logging.getLogger(__name__)

_MIN_ATR = 1.0          # 최소 ATR 보정 (0 나누기 방지)
_SL_ATR_MULT = 1.5      # SL = entry ± 1.5 × ATR


class EMATrendStrategy(BaseStrategy):
    """EMA 배열 기반 추세 추종 전략."""

    name = "ema_trend"

    def __init__(self, timeframe: str = "1h") -> None:
        self._tf = timeframe

    def evaluate(self, inp: StrategyInput) -> StrategySignal:
        tf_data = inp.ta_result.analyses.get(self._tf)
        if tf_data is None:
            return _no_trade(self.name, inp.current_price, f"{self._tf} 타임프레임 데이터 없음")

        ema = tf_data.ema
        macd = tf_data.macd
        atr = max(tf_data.atr, _MIN_ATR)
        price = float(inp.current_price)
        signals: list[str] = []

        # ── LONG 조건 ────────────────────────────────────────────────────────
        long_conditions = (
            ema.ema9 > ema.ema21
            and ema.ema21 > ema.ema50
            and price > ema.ema50
            and macd.histogram > 0
        )
        # ── SHORT 조건 ───────────────────────────────────────────────────────
        short_conditions = (
            ema.ema9 < ema.ema21
            and ema.ema21 < ema.ema50
            and price < ema.ema50
            and macd.histogram < 0
        )

        if not long_conditions and not short_conditions:
            return _no_trade(self.name, inp.current_price, "EMA 배열 불분명 — 추세 미확인")

        direction = "LONG" if long_conditions else "SHORT"

        # ── 신뢰도 계산 ──────────────────────────────────────────────────────
        confidence = 0.55

        # 완전 4선 정렬 보너스
        if direction == "LONG" and ema.ema50 > ema.ema200:
            confidence += 0.10
            signals.append("ema_full_bullish_alignment")
        elif direction == "SHORT" and ema.ema50 < ema.ema200:
            confidence += 0.10
            signals.append("ema_full_bearish_alignment")

        # MACD 골든/데드 크로스
        if (direction == "LONG" and macd.cross == "bullish") or (
            direction == "SHORT" and macd.cross == "bearish"
        ):
            confidence += 0.08
            signals.append(f"macd_{macd.cross}_cross_{self._tf}")

        # 거래량 확인
        if tf_data.volume_ratio >= 1.5:
            confidence += 0.05
            signals.append(f"volume_surge_{self._tf}")
        elif tf_data.volume_ratio >= 1.0:
            confidence += 0.02

        # RSI 방향 확인 (추세와 동일 방향)
        if direction == "LONG" and tf_data.rsi < 60:
            confidence += 0.05
            signals.append(f"rsi_not_overbought_{self._tf}")
        elif direction == "SHORT" and tf_data.rsi > 40:
            confidence += 0.05
            signals.append(f"rsi_not_oversold_{self._tf}")

        # ── TP/SL 계산 ───────────────────────────────────────────────────────
        sl_distance = _SL_ATR_MULT * atr

        reason = (
            f"EMA 배열 {'상승' if direction == 'LONG' else '하락'} "
            f"(EMA9={ema.ema9:.0f} / EMA21={ema.ema21:.0f} / EMA50={ema.ema50:.0f}), "
            f"MACD 히스토그램={macd.histogram:.1f}, ATR={atr:.1f}"
        )

        return _build_signal(
            strategy_name=self.name,
            direction=direction,
            confidence=confidence,
            entry=price,
            sl_distance=sl_distance,
            rr=TARGET_RR,
            signals_fired=signals,
            reason=reason,
        )
