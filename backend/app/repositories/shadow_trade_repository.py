"""Shadow Trade DB 쿼리."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shadow.models import ShadowTradeRecord
from app.models.shadow_trade import ShadowTrade


class ShadowTradeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: ShadowTradeRecord) -> None:
        """ShadowTradeRecord를 DB에 저장한다."""
        orm = ShadowTrade(
            id=uuid.UUID(record.id),
            user_id=record.user_id,
            coin=record.coin,
            symbol=record.symbol,
            direction=record.direction,
            entry_price=record.entry_price,
            tp_price=record.tp_price,
            sl_price=record.sl_price,
            quantity=record.quantity,
            leverage=record.leverage,
            status=record.status,
            opened_at=record.opened_at,
        )
        self._session.add(orm)
        await self._session.flush()

    async def get_open_trades(self, user_id: str | None = None) -> Sequence[ShadowTrade]:
        """OPEN 상태 거래 조회. user_id 지정 시 해당 사용자만 반환."""
        stmt = select(ShadowTrade).where(ShadowTrade.status == "OPEN")
        if user_id is not None:
            stmt = stmt.where(ShadowTrade.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def close_trade(
        self,
        trade_id: uuid.UUID,
        *,
        exit_price: Decimal,
        pnl_usdt: float,
        duration_seconds: float,
        status: str,
        closed_at: datetime,
    ) -> None:
        """TP/SL 체결 확인 후 청산 데이터를 원자적으로 업데이트한다.

        status == "OPEN" 조건을 포함하므로 중복 청산이 발생하지 않는다.
        """
        stmt = (
            update(ShadowTrade)
            .where(ShadowTrade.id == trade_id, ShadowTrade.status == "OPEN")
            .values(
                exit_price=exit_price,
                pnl_usdt=pnl_usdt,
                duration_seconds=duration_seconds,
                status=status,
                closed_at=closed_at,
            )
        )
        await self._session.execute(stmt)
