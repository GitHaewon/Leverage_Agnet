"""
Monitoring System 데이터 모델.

순수 Python dataclass — 외부 의존성 없음.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal


@dataclass
class OrderRecord:
    """단일 주문 시도 기록 (성공/실패 포함)."""
    order_id: str
    symbol: str
    status: Literal["filled", "cancelled", "failed"]
    submitted_at: datetime


@dataclass
class TradeRecord:
    """완료된(청산된) 거래 한 건."""
    trade_id: str
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    realized_pnl: Decimal      # 수수료 차감 후
    closed_at: datetime


@dataclass
class PositionSnapshot:
    """현재 오픈 포지션 스냅샷."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    current_price: Decimal
    quantity: Decimal
    leverage: int
    unrealized_pnl: Decimal


@dataclass
class MetricsSnapshot:
    """
    단일 시점에서 계산된 전체 성과 지표 묶음.

    computed_at: 이 스냅샷이 생성된 UTC 시각
    """
    order_success_rate: Decimal    # 0.0 ~ 1.0 (체결 주문 / 전체 주문)
    win_rate: Decimal              # 0.0 ~ 1.0 (수익 거래 / 전체 청산 거래)
    max_drawdown: Decimal          # 0.0 ~ 1.0 ((고점 - 저점) / 고점)
    daily_pnl: Decimal             # 오늘 실현 PnL + 미실현 PnL (USDT)
    open_positions_count: int      # 현재 오픈 포지션 수

    total_orders: int              # 집계 기준 전체 주문 수
    total_trades: int              # 집계 기준 전체 청산 거래 수

    computed_at: datetime = field(
        default_factory=lambda: datetime.now()
    )
