"""
Trade Journal Repository — DB 쿼리만 담당한다.

비즈니스 로직은 trade_journal_service.py에만 위치한다.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade_journal import TradeJournal
from app.schemas.trade_journal import (
    JournalSearchParams,
    JournalStatsResponse,
    PnLBreakdown,
    TradeJournalCreate,
)


class TradeJournalRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 생성 ─────────────────────────────────────────────────────────────────────

    async def create(self, data: TradeJournalCreate) -> TradeJournal:
        journal = TradeJournal(**data.model_dump())
        self._db.add(journal)
        await self._db.flush()
        await self._db.refresh(journal)
        return journal

    # ── 단건 조회 ─────────────────────────────────────────────────────────────────

    async def get_by_id(self, journal_id: uuid.UUID, user_id: uuid.UUID) -> TradeJournal | None:
        result = await self._db.execute(
            select(TradeJournal).where(
                TradeJournal.id == journal_id,
                TradeJournal.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_trade_log_id(self, trade_log_id: uuid.UUID) -> TradeJournal | None:
        result = await self._db.execute(
            select(TradeJournal).where(TradeJournal.trade_log_id == trade_log_id)
        )
        return result.scalar_one_or_none()

    async def get_by_position_id(self, position_id: uuid.UUID) -> TradeJournal | None:
        result = await self._db.execute(
            select(TradeJournal).where(TradeJournal.position_id == position_id)
        )
        return result.scalar_one_or_none()

    # ── 목록 조회 ─────────────────────────────────────────────────────────────────

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[TradeJournal], int]:
        base_where = TradeJournal.user_id == user_id

        total = await self._count(base_where)
        rows = await self._db.execute(
            select(TradeJournal)
            .where(base_where)
            .order_by(TradeJournal.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(rows.scalars().all()), total

    # ── 검색 ─────────────────────────────────────────────────────────────────────

    async def search(
        self,
        user_id: uuid.UUID,
        params: JournalSearchParams,
    ) -> tuple[list[TradeJournal], int]:
        conditions = [TradeJournal.user_id == user_id]

        if params.coin:
            conditions.append(TradeJournal.coin == params.coin.upper())
        if params.symbol:
            conditions.append(TradeJournal.symbol == params.symbol.upper())
        if params.direction is not None:
            conditions.append(TradeJournal.direction == params.direction)
        if params.close_reason is not None:
            conditions.append(TradeJournal.close_reason == params.close_reason)
        if params.is_ai_trade is not None:
            conditions.append(TradeJournal.is_ai_trade == params.is_ai_trade)
        if params.pnl_min is not None:
            conditions.append(TradeJournal.net_pnl >= params.pnl_min)
        if params.pnl_max is not None:
            conditions.append(TradeJournal.net_pnl <= params.pnl_max)
        if params.entry_from is not None:
            conditions.append(TradeJournal.entry_time >= params.entry_from)
        if params.entry_to is not None:
            conditions.append(TradeJournal.entry_time <= params.entry_to)

        where_clause = and_(*conditions)
        total = await self._count(where_clause)

        rows = await self._db.execute(
            select(TradeJournal)
            .where(where_clause)
            .order_by(TradeJournal.created_at.desc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
        )
        return list(rows.scalars().all()), total

    # ── 수정 ─────────────────────────────────────────────────────────────────────

    async def update_notes(
        self, journal_id: uuid.UUID, user_id: uuid.UUID, user_notes: str | None
    ) -> TradeJournal | None:
        journal = await self.get_by_id(journal_id, user_id)
        if journal is None:
            return None
        journal.user_notes = user_notes
        await self._db.flush()
        await self._db.refresh(journal)
        return journal

    # ── 통계 ─────────────────────────────────────────────────────────────────────

    async def get_stats(
        self,
        user_id: uuid.UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> JournalStatsResponse:
        base_conditions = [TradeJournal.user_id == user_id]
        if from_date:
            base_conditions.append(TradeJournal.entry_time >= from_date)
        if to_date:
            base_conditions.append(TradeJournal.entry_time <= to_date)
        where = and_(*base_conditions)

        # 전체 집계
        agg = await self._db.execute(
            select(
                func.count().label("total"),
                func.count().filter(TradeJournal.net_pnl > 0).label("wins"),
                func.sum(TradeJournal.net_pnl).label("total_pnl"),
                func.sum(
                    func.cast(TradeJournal.net_pnl, Decimal) * 0
                    # fee = net_pnl - (realized_pnl) — 대신 fee는 trade_log에 있으므로 0으로 채움
                    # 실제 구현에서는 trade_logs JOIN이 필요하나 여기선 스냅샷 필드 없음
                ).label("total_fees"),
                func.avg(TradeJournal.net_pnl).label("avg_pnl"),
                func.max(TradeJournal.net_pnl).label("best_pnl"),
                func.min(TradeJournal.net_pnl).label("worst_pnl"),
                func.avg(TradeJournal.duration_seconds).label("avg_duration"),
                func.max(TradeJournal.duration_seconds).label("max_duration"),
                func.min(TradeJournal.duration_seconds).label("min_duration"),
            ).where(where)
        )
        row = agg.one()

        total = row.total or 0
        wins = row.wins or 0
        losses = total - wins
        win_rate = (wins / total) if total > 0 else 0.0

        long_breakdown = await self._direction_breakdown(where, "LONG")
        short_breakdown = await self._direction_breakdown(where, "SHORT")
        close_breakdowns = await self._close_reason_breakdown(where)
        top_coins = await self._coin_breakdown(where, limit=5)

        return JournalStatsResponse(
            from_date=from_date,
            to_date=to_date,
            total_trades=total,
            win_trades=wins,
            loss_trades=losses,
            win_rate=win_rate,
            total_net_pnl=row.total_pnl or Decimal("0"),
            total_fees=Decimal("0"),  # trade_log JOIN 필요 — 추후 확장
            avg_net_pnl=row.avg_pnl or Decimal("0"),
            best_trade_pnl=row.best_pnl,
            worst_trade_pnl=row.worst_pnl,
            avg_duration_seconds=float(row.avg_duration or 0),
            longest_trade_seconds=row.max_duration,
            shortest_trade_seconds=row.min_duration,
            long_breakdown=long_breakdown,
            short_breakdown=short_breakdown,
            close_reason_breakdown=close_breakdowns,
            top_coins=top_coins,
        )

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

    async def _count(self, where_clause) -> int:
        result = await self._db.execute(
            select(func.count()).select_from(TradeJournal).where(where_clause)
        )
        return result.scalar_one() or 0

    async def _direction_breakdown(self, base_where, direction: str) -> PnLBreakdown:
        result = await self._db.execute(
            select(
                func.count().label("total"),
                func.count().filter(TradeJournal.net_pnl > 0).label("wins"),
                func.sum(TradeJournal.net_pnl).label("total_pnl"),
            ).where(and_(base_where, TradeJournal.direction == direction))
        )
        row = result.one()
        total = row.total or 0
        wins = row.wins or 0
        return PnLBreakdown(
            label=direction,
            count=total,
            win_count=wins,
            loss_count=total - wins,
            total_pnl=row.total_pnl or Decimal("0"),
            win_rate=(wins / total) if total > 0 else 0.0,
        )

    async def _close_reason_breakdown(self, base_where) -> list[PnLBreakdown]:
        result = await self._db.execute(
            select(
                TradeJournal.close_reason.label("label"),
                func.count().label("total"),
                func.count().filter(TradeJournal.net_pnl > 0).label("wins"),
                func.sum(TradeJournal.net_pnl).label("total_pnl"),
            ).where(base_where).group_by(TradeJournal.close_reason)
        )
        rows = result.all()
        return [
            PnLBreakdown(
                label=str(r.label),
                count=r.total,
                win_count=r.wins,
                loss_count=r.total - r.wins,
                total_pnl=r.total_pnl or Decimal("0"),
                win_rate=(r.wins / r.total) if r.total > 0 else 0.0,
            )
            for r in rows
        ]

    async def _coin_breakdown(self, base_where, limit: int = 5) -> list[PnLBreakdown]:
        result = await self._db.execute(
            select(
                TradeJournal.coin.label("label"),
                func.count().label("total"),
                func.count().filter(TradeJournal.net_pnl > 0).label("wins"),
                func.sum(TradeJournal.net_pnl).label("total_pnl"),
            )
            .where(base_where)
            .group_by(TradeJournal.coin)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = result.all()
        return [
            PnLBreakdown(
                label=r.label,
                count=r.total,
                win_count=r.wins,
                loss_count=r.total - r.wins,
                total_pnl=r.total_pnl or Decimal("0"),
                win_rate=(r.wins / r.total) if r.total > 0 else 0.0,
            )
            for r in rows
        ]
