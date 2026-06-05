"""
Strategy Engine 데이터 모델.

외부 의존성 없는 순수 Python dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from agents.technical_analysis.models import TechnicalAnalysisResult

Direction = Literal["LONG", "SHORT", "NO_TRADE"]

# TRADING_RULES.md §1.4 신뢰도 → 추천 레버리지
_CONFIDENCE_LEVERAGE: list[tuple[float, int]] = [
    (0.95, 15),
    (0.90, 10),
    (0.80, 7),
    (0.70, 5),
    (0.60, 3),
]


def confidence_to_leverage(confidence: float) -> int:
    """신뢰도를 TRADING_RULES.md §1.4 기준 레버리지로 변환."""
    for threshold, lev in _CONFIDENCE_LEVERAGE:
        if confidence >= threshold:
            return lev
    return 3


@dataclass
class StrategySignal:
    """단일 전략의 출력 시그널."""

    strategy_name: str
    direction: Direction
    confidence: float            # 0.0 ~ 1.0
    entry: Decimal
    take_profit: Decimal | None  # NO_TRADE 시 None
    stop_loss: Decimal | None    # NO_TRADE 시 None
    leverage: int                # 추천 레버리지 (1~20)
    rr_ratio: float              # 계산된 R:R (NO_TRADE = 0.0)
    reason: str
    signals_fired: list[str] = field(default_factory=list)


@dataclass
class StrategyInput:
    """Strategy Engine 입력 데이터."""

    coin: str                          # "BTC" | "ETH"
    symbol: str                        # "BTCUSDT" | "ETHUSDT"
    current_price: Decimal
    ta_result: TechnicalAnalysisResult
    primary_timeframe: str = "1h"


@dataclass
class AggregatedSignal:
    """여러 전략의 다수결 통합 시그널."""

    direction: Direction
    confidence: float
    entry: Decimal
    take_profit: Decimal | None
    stop_loss: Decimal | None
    leverage: int
    rr_ratio: float
    reasons: list[str]
    contributing_strategies: list[str]
    all_signals: list[StrategySignal] = field(default_factory=list)
