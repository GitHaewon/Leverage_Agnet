from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade_log import TradeLog


class TradeLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_daily_loss_usdt(self, user_id: uuid.UUID) -> Decimal:
        """
        오늘 UTC 기준 확정 손실 합계 (§4.2).
        net_pnl < 0인 거래의 절댓값 합산.
        """
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await self._db.execute(
            select(func.sum(TradeLog.net_pnl)).where(
                TradeLog.user_id == user_id,
                TradeLog.created_at >= today_start,
                TradeLog.net_pnl < 0,
            )
        )
        value = result.scalar_one_or_none()
        return abs(value) if value is not None else Decimal("0")

    async def get_weekly_loss_usdt(
        self, user_id: uuid.UUID, week_start: datetime
    ) -> Decimal:
        """이번 주 UTC 기준 확정 손실 합계 (§5)."""
        result = await self._db.execute(
            select(func.sum(TradeLog.net_pnl)).where(
                TradeLog.user_id == user_id,
                TradeLog.created_at >= week_start,
                TradeLog.net_pnl < 0,
            )
        )
        value = result.scalar_one_or_none()
        return abs(value) if value is not None else Decimal("0")

    async def get_consecutive_losses(self, user_id: uuid.UUID, limit: int = 10) -> int:
        """
        가장 최근 거래부터 역순으로 연속 손실 횟수 계산 (§6.2).
        수익 거래가 나오는 순간 중단.
        """
        result = await self._db.execute(
            select(TradeLog.net_pnl)
            .where(TradeLog.user_id == user_id)
            .order_by(TradeLog.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()

        count = 0
        for pnl in rows:
            if pnl < 0:
                count += 1
            else:
                break
        return count

    async def get_recent_trades(
        self, user_id: uuid.UUID, limit: int = 10
    ) -> list[TradeLog]:
        result = await self._db.execute(
            select(TradeLog)
            .where(TradeLog.user_id == user_id)
            .order_by(TradeLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
