"""
CoachingService — 비즈니스 로직.

DB에서 데이터를 수집하고 TradingCoach 에이전트를 호출한 뒤
결과를 저장한다.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.trading_coach import CoachInput, run_coaching
from app.models.coaching_report import CoachingReport
from app.models.reflection_report import ReflectionReport
from app.models.trade_journal import TradeJournal
from app.repositories.coaching_repository import CoachingRepository
from app.schemas.coaching import (
    CoachingReportCreate,
    CoachingReportResponse,
    JournalData,
)

logger = logging.getLogger(__name__)


class CoachingNotFoundError(Exception):
    pass


class CoachingService:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CoachingRepository(session)

    # ── 메인: 주간 코칭 실행 ──────────────────────────────────────────────────

    async def run_weekly_coaching(
        self,
        user_id: uuid.UUID,
        period_days: int = 28,
    ) -> CoachingReport:
        """
        period_days 기간의 거래를 분석하여 CoachingReport를 생성한다.

        동일 period_end 리포트가 이미 존재하면 기존 리포트를 반환한다 (멱등).
        """
        now = datetime.now(timezone.utc)
        period_end   = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = period_end - timedelta(days=period_days)

        existing = await self._repo.get_by_period(user_id, period_end)
        if existing:
            logger.info("coaching report already exists user=%s period=%s", user_id, period_end)
            return existing

        journals = await self._load_journals(user_id, period_start, period_end)
        mistakes = await self._load_mistakes(user_id, period_start, period_end)

        inp = CoachInput(
            user_id=str(user_id),
            period_start=period_start,
            period_end=period_end,
            journals=journals,
            reflection_mistakes=mistakes,
        )

        result = await run_coaching(inp)

        create_data = CoachingReportCreate(
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
            overall_stats=result.overall_stats,
            hourly_stats=[h.model_dump() for h in result.hourly_stats],
            weekday_stats=[w.model_dump() for w in result.weekday_stats],
            coin_stats=[c.model_dump() for c in result.coin_stats],
            strategy_stats=[s.model_dump() for s in result.strategy_stats],
            repeated_mistakes=[m.model_dump() for m in result.repeated_mistakes],
            emotional_patterns=[p.model_dump() for p in result.emotional_patterns],
            risk_behavior_score=result.risk_behavior_score,
            coach_summary=result.coach_summary,
            strengths=result.strengths,
            blind_spots=result.blind_spots,
            weekly_goal=result.weekly_goal,
            skip_reason=result.skip_reason,
            model_used=result.model_used,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

        report = await self._repo.create(create_data)
        await self._session.commit()

        logger.info(
            "coaching report created user=%s period=%s~%s trades=%d",
            user_id, period_start.date(), period_end.date(),
            result.overall_stats.get("total_trades", 0),
        )
        return report

    # ── 조회 ──────────────────────────────────────────────────────────────────

    async def get_latest_report(self, user_id: uuid.UUID) -> CoachingReportResponse:
        report = await self._repo.get_latest_by_user(user_id)
        if not report:
            raise CoachingNotFoundError(f"코칭 리포트가 없습니다: user={user_id}")
        return CoachingReportResponse.model_validate(report)

    async def list_reports(
        self, user_id: uuid.UUID, page: int = 1, size: int = 10
    ) -> dict:
        reports, total = await self._repo.list_by_user(user_id, page=page, size=size)
        return {
            "items": [CoachingReportResponse.model_validate(r) for r in reports],
            "total": total,
            "page": page,
            "size": size,
        }

    # ── 내부: 데이터 수집 ─────────────────────────────────────────────────────

    async def _load_journals(
        self,
        user_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> list[JournalData]:
        stmt = select(TradeJournal).where(
            TradeJournal.user_id == user_id,
            TradeJournal.entry_time >= period_start,
            TradeJournal.entry_time < period_end,
            TradeJournal.deleted_at.is_(None),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            JournalData(
                coin=j.coin,
                direction=j.direction,
                net_pnl=float(j.net_pnl),
                entry_time=j.entry_time,
                duration_seconds=j.duration_seconds,
                close_reason=j.close_reason,
                strategy=j.strategy,
                leverage=j.leverage,
                pnl_percentage=float(j.pnl_percentage),
            )
            for j in rows
        ]

    async def _load_mistakes(
        self,
        user_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> list[str]:
        """ReflectionReport.mistakes 필드를 평탄화하여 반환한다."""
        stmt = select(ReflectionReport).where(
            ReflectionReport.user_id == user_id,
            ReflectionReport.created_at >= period_start,
            ReflectionReport.created_at < period_end,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        mistakes: list[str] = []
        for r in rows:
            mistakes.extend(r.mistakes or [])
        return mistakes
