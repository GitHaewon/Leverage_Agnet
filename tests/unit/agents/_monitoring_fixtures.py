"""
Monitoring System 테스트 공통 픽스처 헬퍼.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from agents.monitoring.models import OrderRecord, PositionSnapshot, TradeRecord

_TODAY = date(2026, 6, 7)
_NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


# ── 날짜 헬퍼 ────────────────────────────────────────────────────────────────────

def today() -> date:
    return _TODAY


def now_at(hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 6, 7, hour, minute, 0, tzinfo=timezone.utc)


def yesterday_at(hour: int = 12) -> datetime:
    return datetime(2026, 6, 6, hour, 0, 0, tzinfo=timezone.utc)


# ── OrderRecord 헬퍼 ─────────────────────────────────────────────────────────────

def make_order(
    order_id: str = "ord-001",
    status: str = "filled",
    symbol: str = "BTCUSDT",
    **kwargs: Any,
) -> OrderRecord:
    return OrderRecord(
        order_id=order_id,
        symbol=symbol,
        status=status,
        submitted_at=kwargs.get("submitted_at", _NOW),
    )


def make_orders(statuses: list[str]) -> list[OrderRecord]:
    return [
        make_order(order_id=f"ord-{i:03d}", status=s)
        for i, s in enumerate(statuses, 1)
    ]


# ── TradeRecord 헬퍼 ─────────────────────────────────────────────────────────────

def make_trade(
    trade_id: str = "trd-001",
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    realized_pnl: float = 150.0,
    closed_today: bool = True,
    **kwargs: Any,
) -> TradeRecord:
    closed_at = now_at(10) if closed_today else yesterday_at()
    return TradeRecord(
        trade_id=trade_id,
        symbol=symbol,
        direction=direction,
        entry_price=Decimal("67000"),
        exit_price=Decimal("69000"),
        quantity=Decimal("0.001"),
        realized_pnl=Decimal(str(realized_pnl)),
        closed_at=kwargs.get("closed_at", closed_at),
    )


def make_trades(pnls: list[float], closed_today: bool = True) -> list[TradeRecord]:
    return [
        make_trade(
            trade_id=f"trd-{i:03d}",
            realized_pnl=pnl,
            closed_today=closed_today,
        )
        for i, pnl in enumerate(pnls, 1)
    ]


# ── PositionSnapshot 헬퍼 ────────────────────────────────────────────────────────

def make_position(
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    unrealized_pnl: float = 50.0,
    leverage: int = 5,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        direction=direction,
        entry_price=Decimal("67000"),
        current_price=Decimal("67500"),
        quantity=Decimal("0.001"),
        leverage=leverage,
        unrealized_pnl=Decimal(str(unrealized_pnl)),
    )


def make_balance_history(values: list[float]) -> list[Decimal]:
    return [Decimal(str(v)) for v in values]
