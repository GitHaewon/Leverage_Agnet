"""
CoachingReport Repository — DB 쿼리만 담당한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coaching_report import CoachingReport
from app.schemas.coaching import CoachingReportCreate


class CoachingRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: CoachingReportCreate) -> CoachingReport:
        report = CoachingReport(
            user_id=data.user_id,
            period_start=data.period_start,
            period_end=data.period_end,
            overall_stats=data.overall_stats,
            hourly_stats=data.hourly_stats,
            weekday_stats=data.weekday_stats,
            coin_stats=data.coin_stats,
            strategy_stats=data.strategy_stats,
            repeated_mistakes=data.repeated_mistakes,
            emotional_patterns=data.emotional_patterns,
            risk_behavior_score=data.risk_behavior_score,
            coach_summary=data.coach_summary,
            strengths=data.strengths,
            blind_spots=data.blind_spots,
            weekly_goal=data.weekly_goal,
            skip_reason=data.skip_reason,
            model_used=data.model_used,
            tokens_input=data.tokens_input,
            tokens_output=data.tokens_output,
        )
        self._session.add(report)
        await self._session.flush()
        await self._session.refresh(report)
        return report

    async def get_by_id(
        self, report_id: uuid.UUID, user_id: uuid.UUID
    ) -> CoachingReport | None:
        stmt = select(CoachingReport).where(
            CoachingReport.id == report_id,
            CoachingReport.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_by_user(self, user_id: uuid.UUID) -> CoachingReport | None:
        stmt = (
            select(CoachingReport)
            .where(CoachingReport.user_id == user_id)
            .order_by(CoachingReport.period_end.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_period(
        self, user_id: uuid.UUID, period_end: datetime
    ) -> CoachingReport | None:
        """동일 기간 리포트 조회 (멱등성 체크용)."""
        stmt = select(CoachingReport).where(
            CoachingReport.user_id == user_id,
            CoachingReport.period_end == period_end,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        size: int = 10,
    ) -> tuple[list[CoachingReport], int]:
        count_stmt = select(func.count()).where(
            CoachingReport.user_id == user_id
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(CoachingReport)
            .where(CoachingReport.user_id == user_id)
            .order_by(CoachingReport.period_end.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(rows), total
