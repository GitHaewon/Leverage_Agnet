"""
Strategy → Risk Engine 연동 브리지.

StrategySignal / AggregatedSignal을 RiskEngine.validate()가 받는
RawSignal로 변환한다.

변환 규칙:
  NO_TRADE → direction="HOLD" (RiskEngine이 즉시 거부하고 실행 없음)
  LONG/SHORT → 그대로 전달
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from agents.risk.models import RawSignal
from agents.strategy.models import AggregatedSignal, StrategySignal


def strategy_signal_to_raw(
    signal: StrategySignal,
    coin: str,
    symbol: str,
    signal_id: uuid.UUID | None = None,
) -> RawSignal:
    """
    단일 전략 시그널을 RawSignal로 변환.

    NO_TRADE는 Risk Engine이 인식하는 HOLD로 변환되어
    어떤 주문도 실행되지 않는다.
    """
    direction = signal.direction if signal.direction != "NO_TRADE" else "HOLD"

    return RawSignal(
        direction=direction,
        coin=coin,
        symbol=symbol,
        confidence=signal.confidence,
        entry_price=signal.entry,
        take_profit=signal.take_profit,
        stop_loss=signal.stop_loss,
        leverage=signal.leverage,
        signal_id=signal_id,
    )


def aggregated_signal_to_raw(
    signal: AggregatedSignal,
    coin: str,
    symbol: str,
    signal_id: uuid.UUID | None = None,
) -> RawSignal:
    """
    통합 시그널을 RawSignal로 변환.

    StrategyEngine.evaluate() 결과를 그대로 전달하는 권장 경로.
    """
    direction = signal.direction if signal.direction != "NO_TRADE" else "HOLD"

    return RawSignal(
        direction=direction,
        coin=coin,
        symbol=symbol,
        confidence=signal.confidence,
        entry_price=signal.entry,
        take_profit=signal.take_profit,
        stop_loss=signal.stop_loss,
        leverage=signal.leverage,
        signal_id=signal_id,
    )
