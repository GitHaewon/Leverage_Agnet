"""
Coaching Celery Worker.

두 가지 태스크:
  run_coaching_for_user       — 특정 사용자 1인 코칭 (수동 트리거)
  run_weekly_coaching_all_users — 모든 활성 사용자 일괄 코칭 (Beat 스케줄)
"""
from __future__ import annotations

import logging
import uuid

from celery import Task

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.coaching_worker.run_coaching_for_user",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
)
def run_coaching_for_user(
    self: Task,
    user_id: str,
    period_days: int = 28,
) -> dict:
    """특정 사용자의 주간 코칭 리포트를 생성한다."""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings
    from app.services.coaching_service import CoachingService

    async def _run() -> dict:
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            service = CoachingService(session)
            report = await service.run_weekly_coaching(
                user_id=uuid.UUID(user_id),
                period_days=period_days,
            )
            return {
                "status": "ok",
                "report_id": str(report.id),
                "skip_reason": report.skip_reason,
                "risk_score": report.risk_behavior_score,
            }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("coaching task failed user=%s: %s", user_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    name="app.workers.coaching_worker.run_weekly_coaching_all_users",
    acks_late=True,
)
def run_weekly_coaching_all_users() -> dict:
    """
    모든 활성 사용자에게 주간 코칭 리포트를 생성한다.

    Celery Beat: 매주 월요일 00:00 UTC (KST 09:00) 실행.
    """
    import asyncio
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings

    async def _fetch_active_users() -> list[str]:
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            result = await session.execute(
                text("SELECT id FROM users WHERE is_active = true AND deleted_at IS NULL")
            )
            return [str(row[0]) for row in result.fetchall()]

    user_ids = asyncio.run(_fetch_active_users())
    dispatched = 0

    for uid in user_ids:
        run_coaching_for_user.delay(user_id=uid, period_days=28)
        dispatched += 1

    logger.info("weekly coaching dispatched for %d users", dispatched)
    return {"dispatched": dispatched}
