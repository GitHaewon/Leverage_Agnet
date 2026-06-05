from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position
from app.models.enums import PositionStatusType
from agents.risk.models import OpenPosition


class PositionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def count_open(self, user_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(func.count(Position.id)).where(
                Position.user_id == user_id,
                Position.status == PositionStatusType.OPEN,
            )
        )
        return result.scalar_one() or 0

    async def get_open_by_coin(
        self, user_id: uuid.UUID, coin: str
    ) -> Position | None:
        result = await self._db.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.coin == coin,
                Position.status == PositionStatusType.OPEN,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_open(self, user_id: uuid.UUID) -> list[Position]:
        result = await self._db.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.status == PositionStatusType.OPEN,
            )
        )
        return list(result.scalars().all())

    async def calculate_open_risk_usdt(self, user_id: uuid.UUID) -> Decimal:
        """
        오픈 포지션들의 예상 최대 손실 합계.
        각 포지션: |entry - stop_loss| × quantity
        """
        positions = await self.get_all_open(user_id)
        total_risk = Decimal("0")
        for pos in positions:
            if pos.stop_loss is not None and pos.entry_price > 0:
                sl_dist = abs(pos.entry_price - pos.stop_loss)
                total_risk += sl_dist * pos.quantity
        return total_risk

    async def get_open_as_risk_model(
        self, user_id: uuid.UUID, coin: str
    ) -> OpenPosition | None:
        """Risk Engine에서 사용하는 OpenPosition 모델로 변환."""
        pos = await self.get_open_by_coin(user_id, coin)
        if pos is None:
            return None

        # DCA 횟수 계산 (orders 테이블에서)
        from sqlalchemy import select as sa_select, func as sa_func
        from app.models.order import Order
        from app.models.enums import OrderPurposeType, OrderStatusType

        dca_result = await self._db.execute(
            sa_select(sa_func.count(Order.id)).where(
                Order.position_id == pos.id,
                Order.purpose == OrderPurposeType.DCA,
                Order.status == OrderStatusType.FILLED,
            )
        )
        dca_count = dca_result.scalar_one() or 0

        return OpenPosition(
            id=pos.id,
            coin=pos.coin,
            symbol=pos.symbol,
            direction=pos.direction.value if hasattr(pos.direction, "value") else str(pos.direction),
            entry_price=pos.entry_price,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            leverage=pos.leverage,
            dca_count=dca_count,
        )
