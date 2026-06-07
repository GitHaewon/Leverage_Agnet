"""
Monitoring 지표 계산 순수 함수.

모든 계산은 Decimal 산술을 사용하며 I/O가 없다.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from agents.monitoring.models import OrderRecord, PositionSnapshot, TradeRecord

_ZERO = Decimal("0")
_ONE = Decimal("1")


def order_success_rate(orders: list[OrderRecord]) -> Decimal:
    """체결 주문 비율 = filled / total.

    주문이 없으면 0 반환.
    """
    if not orders:
        return _ZERO
    filled = sum(1 for o in orders if o.status == "filled")
    return Decimal(str(filled)) / Decimal(str(len(orders)))


def win_rate(trades: list[TradeRecord]) -> Decimal:
    """수익 거래 비율 = (realized_pnl > 0 거래) / 전체 청산 거래.

    거래가 없으면 0 반환.
    """
    if not trades:
        return _ZERO
    wins = sum(1 for t in trades if t.realized_pnl > _ZERO)
    return Decimal(str(wins)) / Decimal(str(len(trades)))


def max_drawdown(balance_history: list[Decimal]) -> Decimal:
    """최대 낙폭 = (고점 - 저점) / 고점.

    데이터 포인트가 2개 미만이면 0 반환.
    고점이 0 이하면 0 반환 (나눗셈 방지).
    """
    if len(balance_history) < 2:
        return _ZERO

    peak = _ZERO
    max_dd = _ZERO

    for balance in balance_history:
        if balance > peak:
            peak = balance
        if peak > _ZERO:
            dd = (peak - balance) / peak
            if dd > max_dd:
                max_dd = dd

    return max_dd


def daily_pnl(
    trades: list[TradeRecord],
    positions: list[PositionSnapshot],
    today: date,
) -> Decimal:
    """오늘 PnL = 오늘 청산된 realized PnL 합 + 모든 오픈 포지션 unrealized PnL 합."""
    realized = sum(
        (t.realized_pnl for t in trades if t.closed_at.date() == today),
        _ZERO,
    )
    unrealized = sum(
        (p.unrealized_pnl for p in positions),
        _ZERO,
    )
    return realized + unrealized


def open_positions_count(positions: list[PositionSnapshot]) -> int:
    """현재 오픈 포지션 수."""
    return len(positions)
