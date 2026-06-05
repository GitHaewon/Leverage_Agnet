"""
Strategy 추상 베이스 클래스.

모든 전략은 BaseStrategy를 상속하고 evaluate()를 구현한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from agents.strategy.models import Direction, StrategyInput, StrategySignal, confidence_to_leverage

# 목표 R:R 비율 — TRADING_RULES.md §7.4 최솟값 2.0의 안전 마진
TARGET_RR = 2.5
MIN_RR = 2.0


def _no_trade(strategy_name: str, entry: Decimal, reason: str) -> StrategySignal:
    """NO_TRADE 시그널 생성 헬퍼."""
    return StrategySignal(
        strategy_name=strategy_name,
        direction="NO_TRADE",
        confidence=0.0,
        entry=entry,
        take_profit=None,
        stop_loss=None,
        leverage=1,
        rr_ratio=0.0,
        reason=reason,
    )


def _build_signal(
    strategy_name: str,
    direction: Direction,
    confidence: float,
    entry: float,
    sl_distance: float,   # 항상 양수 (가격 단위)
    rr: float = TARGET_RR,
    signals_fired: list[str] | None = None,
    reason: str = "",
) -> StrategySignal:
    """
    entry / sl_distance / rr 로 TP, SL, leverage 를 계산해 StrategySignal을 만든다.
    LONG: SL = entry - sl_distance, TP = entry + sl_distance*rr
    SHORT: SL = entry + sl_distance, TP = entry - sl_distance*rr
    """
    assert sl_distance > 0, "sl_distance must be positive"

    if direction == "LONG":
        sl = entry - sl_distance
        tp = entry + sl_distance * rr
    else:  # SHORT
        sl = entry + sl_distance
        tp = entry - sl_distance * rr

    actual_rr = rr  # by construction

    lev = confidence_to_leverage(confidence)

    return StrategySignal(
        strategy_name=strategy_name,
        direction=direction,
        confidence=round(min(confidence, 1.0), 4),
        entry=Decimal(str(round(entry, 2))),
        take_profit=Decimal(str(round(tp, 2))),
        stop_loss=Decimal(str(round(sl, 2))),
        leverage=lev,
        rr_ratio=round(actual_rr, 2),
        reason=reason,
        signals_fired=signals_fired or [],
    )


class BaseStrategy(ABC):
    """모든 전략의 추상 기반 클래스."""

    name: str

    @abstractmethod
    def evaluate(self, inp: StrategyInput) -> StrategySignal:
        """시장 데이터를 분석하여 StrategySignal을 반환한다."""
        ...
