"""
Reflection Repository — DB 쿼리만 담당한다.

비즈니스 로직은 reflection_service.py에만 위치한다.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reflection_report import ReflectionReport
from app.schemas.reflection import ReflectionReportCreate


class ReflectionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 생성 ─────────────────────────────────────────────────────────────────────

    async def create(self, data: ReflectionReportCreate) -> ReflectionReport:
        report = ReflectionReport(**data.model_dump())
        self._db.add(report)
        await self._db.flush()
        await self._db.refresh(report)
        return report

    # ── 단건 조회 ─────────────────────────────────────────────────────────────────

    async def get_by_id(
        self, report_id: uuid.UUID, user_id: uuid.UUID
    ) -> ReflectionReport | None:
        result = await self._db.execute(
            select(ReflectionReport).where(
                ReflectionReport.id == report_id,
                ReflectionReport.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_position_id(
        self, position_id: uuid.UUID
    ) -> ReflectionReport | None:
        result = await self._db.execute(
            select(ReflectionReport).where(
                ReflectionReport.position_id == position_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_position_id_and_user(
        self, position_id: uuid.UUID, user_id: uuid.UUID
    ) -> ReflectionReport | None:
        result = await self._db.execute(
            select(ReflectionReport).where(
                ReflectionReport.position_id == position_id,
                ReflectionReport.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    # ── 목록 조회 ─────────────────────────────────────────────────────────────────

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[ReflectionReport], int]:
        from sqlalchemy import func

        total_result = await self._db.execute(
            select(func.count())
            .select_from(ReflectionReport)
            .where(ReflectionReport.user_id == user_id)
        )
        total = total_result.scalar_one() or 0

        rows = await self._db.execute(
            select(ReflectionReport)
            .where(ReflectionReport.user_id == user_id)
            .order_by(ReflectionReport.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(rows.scalars().all()), total
