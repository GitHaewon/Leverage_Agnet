"""
MetricsCollector — 모든 원시 데이터를 받아 MetricsSnapshot을 생성하는 퍼사드.

순수 도메인 레이어: I/O 없음, 외부 의존성 없음.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from agents.monitoring.calculator import (
    daily_pnl as _daily_pnl,
    max_drawdown as _max_drawdown,
    open_positions_count as _open_count,
    order_success_rate as _order_success_rate,
    win_rate as _win_rate,
)
from agents.monitoring.models import (
    MetricsSnapshot,
    OrderRecord,
    PositionSnapshot,
    TradeRecord,
)


class MetricsCollector:
    """
    원시 거래 데이터 → MetricsSnapshot 변환기.

    snapshot() 호출 시마다 새로운 스냅샷을 계산한다.
    상태를 보유하지 않으므로 thread-safe.
    """

    def snapshot(
        self,
        orders: list[OrderRecord],
        trades: list[TradeRecord],
        positions: list[PositionSnapshot],
        balance_history: list[Decimal],
        today: date | None = None,
    ) -> MetricsSnapshot:
        """
        Parameters
        ----------
        orders:          전체 주문 기록 (체결/취소/실패 모두 포함)
        trades:          전체 청산 거래 기록
        positions:       현재 오픈 포지션 목록
        balance_history: 잔고 시계열 (시간순 오름차순)
        today:           PnL 기준 날짜 (None이면 UTC 오늘)
        """
        _today = today or datetime.now(timezone.utc).date()

        return MetricsSnapshot(
            order_success_rate=_order_success_rate(orders),
            win_rate=_win_rate(trades),
            max_drawdown=_max_drawdown(balance_history),
            daily_pnl=_daily_pnl(trades, positions, _today),
            open_positions_count=_open_count(positions),
            total_orders=len(orders),
            total_trades=len(trades),
            computed_at=datetime.now(timezone.utc),
        )
