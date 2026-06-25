"""
Strategy Engine — 세 전략 오케스트레이션 및 다수결 집계.

사용 흐름:
  engine = StrategyEngine()
  result = engine.evaluate(inp)     # AggregatedSignal 반환
"""
from __future__ import annotations

import logging

from agents.strategy.base import BaseStrategy
from agents.strategy.breakout import BreakoutStrategy
from agents.strategy.ema_trend import EMATrendStrategy
from agents.strategy.models import (
    AggregatedSignal,
    StrategyCandidate,
    StrategyInput,
    StrategySignal,
    confidence_to_leverage,
)
from agents.strategy.rsi_reversal import RSIReversalStrategy
from agents.decision.strategy_selector import is_strategy_allowed_for_regime

logger = logging.getLogger(__name__)

_ALL_STRATEGY_NAMES = ("ema_trend", "rsi_reversal", "breakout")

_SIGNAL_TO_CANDIDATE_NAME: dict[str, str] = {
    "ema_trend": "TREND_PULLBACK",
    "breakout": "BREAKOUT_RETEST",
    "rsi_reversal": "RANGE_MEAN_REVERSION",
}


def _build_strategies(names: tuple[str, ...], timeframe: str) -> list[BaseStrategy]:
    mapping: dict[str, BaseStrategy] = {
        "ema_trend":   EMATrendStrategy(timeframe),
        "rsi_reversal": RSIReversalStrategy(timeframe),
        "breakout":    BreakoutStrategy(timeframe),
    }
    return [mapping[n] for n in names if n in mapping]


class StrategyEngine:
    """
    세 가지 전략을 병렬 평가하고 다수결로 최종 방향을 결정한다.

    집계 규칙:
      - LONG 다수 → LONG (가장 높은 신뢰도 전략의 TP/SL 사용)
      - SHORT 다수 → SHORT
      - 동수 or 전략 없음 → NO_TRADE
      - 최소 신뢰도(min_confidence) 미달 → NO_TRADE
    """

    def __init__(
        self,
        enabled: tuple[str, ...] = _ALL_STRATEGY_NAMES,
        primary_timeframe: str = "1h",
        min_confidence: float = 0.60,
    ) -> None:
        self._strategies = _build_strategies(enabled, primary_timeframe)
        self._min_confidence = min_confidence

    def evaluate(self, inp: StrategyInput) -> AggregatedSignal:
        """모든 전략 실행 → 집계 → AggregatedSignal 반환."""
        signals = [s.evaluate(inp) for s in self._strategies]

        agg = _aggregate(signals, inp)
        agg.candidates = build_strategy_candidates(signals, market_regime=None)

        logger.debug(
            "StrategyEngine coin=%s direction=%s confidence=%.2f strategies=%s",
            inp.coin, agg.direction, agg.confidence,
            agg.contributing_strategies,
        )

        # 최소 신뢰도 미달 시 NO_TRADE 강제
        if agg.direction != "NO_TRADE" and agg.confidence < self._min_confidence:
            return AggregatedSignal(
                direction="NO_TRADE",
                confidence=agg.confidence,
                entry=inp.current_price,
                take_profit=None,
                stop_loss=None,
                leverage=1,
                rr_ratio=0.0,
                reasons=[f"통합 신뢰도 {agg.confidence:.0%} < 최소 {self._min_confidence:.0%}"],
                contributing_strategies=[],
                all_signals=signals,
            )

        return agg

    def generate_candidates(
        self,
        inp: StrategyInput,
        market_regime: object,
    ) -> list[StrategyCandidate]:
        """시장 국면에 허용되는 전략 후보들을 생성한다.

        기존 전략 evaluate() 결과를 StrategyCandidate로 변환하는 adapter이며,
        AggregatedSignal 다수결 동작은 변경하지 않는다.
        """
        signals = [s.evaluate(inp) for s in self._strategies]
        return build_strategy_candidates(signals, market_regime)


def build_strategy_candidates(
    signals: list[StrategySignal],
    market_regime: object | None,
) -> list[StrategyCandidate]:
    """StrategySignal 목록을 국면별 StrategyCandidate 목록으로 변환한다."""
    candidates: list[StrategyCandidate] = []
    for sig in signals:
        candidate_name = _SIGNAL_TO_CANDIDATE_NAME.get(
            sig.strategy_name,
            sig.strategy_name.upper(),
        )
        if market_regime is not None and not is_strategy_allowed_for_regime(
            candidate_name,
            market_regime,
        ):
            continue
        if sig.direction not in ("LONG", "SHORT"):
            continue
        if sig.take_profit is None or sig.stop_loss is None:
            continue
        if sig.rr_ratio <= 0:
            continue
        candidates.append(
            StrategyCandidate(
                strategy_name=candidate_name,
                source_strategy=sig.strategy_name,
                direction=sig.direction,
                confidence=sig.confidence,
                entry=sig.entry,
                take_profit=sig.take_profit,
                stop_loss=sig.stop_loss,
                leverage=sig.leverage,
                rr_ratio=sig.rr_ratio,
                reason=sig.reason,
                signals_fired=list(sig.signals_fired),
            )
        )
    return sorted(candidates, key=lambda c: (c.confidence, c.rr_ratio), reverse=True)


def _aggregate(signals: list[StrategySignal], inp: StrategyInput) -> AggregatedSignal:
    """다수결 집계."""
    long_sigs  = [s for s in signals if s.direction == "LONG"]
    short_sigs = [s for s in signals if s.direction == "SHORT"]

    if len(long_sigs) > len(short_sigs) and long_sigs:
        chosen, direction = long_sigs, "LONG"
    elif len(short_sigs) > len(long_sigs) and short_sigs:
        chosen, direction = short_sigs, "SHORT"
    else:
        return AggregatedSignal(
            direction="NO_TRADE",
            confidence=0.0,
            entry=inp.current_price,
            take_profit=None,
            stop_loss=None,
            leverage=1,
            rr_ratio=0.0,
            reasons=["전략 합의 없음 — NO_TRADE"],
            contributing_strategies=[],
            all_signals=signals,
        )

    avg_confidence = sum(s.confidence for s in chosen) / len(chosen)
    best = max(chosen, key=lambda s: s.confidence)

    return AggregatedSignal(
        direction=direction,
        confidence=round(avg_confidence, 4),
        entry=best.entry,
        take_profit=best.take_profit,
        stop_loss=best.stop_loss,
        leverage=confidence_to_leverage(avg_confidence),
        rr_ratio=best.rr_ratio,
        reasons=[s.reason for s in chosen],
        contributing_strategies=[s.strategy_name for s in chosen],
        all_signals=signals,
    )
