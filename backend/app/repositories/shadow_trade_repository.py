"""Shadow Trade DB 쿼리."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shadow.models import ShadowTradeRecord
from app.models.shadow_trade import ShadowTrade
from app.schemas.shadow_trades import ShadowTradeStats


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

    async def list_trades(
        self,
        user_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[ShadowTrade], int]:
        """사용자의 shadow trades 목록과 총 개수를 반환한다."""
        stmt = select(ShadowTrade).where(ShadowTrade.user_id == user_id)
        if status:
            stmt = stmt.where(ShadowTrade.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(ShadowTrade.opened_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all(), total

    async def get_stats(self, user_id: str) -> ShadowTradeStats:
        """사용자의 shadow trading 집계 통계를 반환한다."""
        stmt = select(ShadowTrade).where(ShadowTrade.user_id == user_id)
        all_trades = (await self._session.execute(stmt)).scalars().all()

        total = len(all_trades)
        open_trades = sum(1 for t in all_trades if t.status == "OPEN")
        tp_hit = sum(1 for t in all_trades if t.status == "TP_HIT")
        sl_hit = sum(1 for t in all_trades if t.status == "SL_HIT")
        closed = tp_hit + sl_hit

        closed_pnls = [t.pnl_usdt for t in all_trades if t.pnl_usdt is not None]
        total_pnl = sum(closed_pnls) if closed_pnls else 0.0
        avg_pnl = total_pnl / len(closed_pnls) if closed_pnls else 0.0
        best_pnl = max(closed_pnls) if closed_pnls else None
        worst_pnl = min(closed_pnls) if closed_pnls else None

        durations = [t.duration_seconds for t in all_trades if t.duration_seconds is not None]
        avg_duration_min = (sum(durations) / len(durations) / 60.0) if durations else None

        win_rate = (tp_hit / closed * 100.0) if closed > 0 else 0.0

        return ShadowTradeStats(
            total_trades=total,
            open_trades=open_trades,
            closed_trades=closed,
            tp_hit=tp_hit,
            sl_hit=sl_hit,
            win_rate=round(win_rate, 1),
            total_pnl_usdt=round(total_pnl, 2),
            avg_pnl_usdt=round(avg_pnl, 2),
            best_pnl_usdt=round(best_pnl, 2) if best_pnl is not None else None,
            worst_pnl_usdt=round(worst_pnl, 2) if worst_pnl is not None else None,
            avg_duration_minutes=round(avg_duration_min, 1) if avg_duration_min is not None else None,
        )

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
