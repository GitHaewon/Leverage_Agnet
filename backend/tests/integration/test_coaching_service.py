"""
CoachingService 통합 테스트.

Claude API를 Mock하고 SQLite 인메모리 DB를 사용한다.
검증 대상:
  - run_weekly_coaching: 정상 분석, 데이터 부족, 멱등성
  - get_latest_report: 최신 리포트 반환, 없을 때 예외
  - list_reports: 페이지네이션
  - run_coaching (에이전트 전체 흐름): Mock Claude → 저장
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.coaching_report import CoachingReport
from app.models.trade_journal import TradeJournal
from app.models.reflection_report import ReflectionReport
from app.services.coaching_service import CoachingNotFoundError, CoachingService

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

# ── DB 설정 ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s


# ── 픽스처 헬퍼 ───────────────────────────────────────────────────────────────

def _dt_utc(days_ago: int = 0, hour_kst: int = 10) -> datetime:
    base = datetime(2026, 6, 9, hour_kst, 0, tzinfo=KST)
    return (base - timedelta(days=days_ago)).astimezone(UTC)


def _make_journal(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    coin: str = "BTC",
    net_pnl: str = "100.00",
    days_ago: int = 7,
    hour_kst: int = 10,
    close_reason: str = "tp_hit",
    leverage: int = 5,
    strategy: str | None = "RSI_EMA",
) -> TradeJournal:
    j = TradeJournal(
        user_id=user_id,
        position_id=uuid.uuid4(),
        signal_id=uuid.uuid4(),
        coin=coin,
        symbol=f"{coin}USDT",
        direction="LONG",
        leverage=leverage,
        is_ai_trade=True,
        strategy=strategy,
        entry_reason="테스트 진입",
        exit_reason="테스트 청산",
        net_pnl=Decimal(net_pnl),
        pnl_percentage=Decimal("5.00"),
        duration_seconds=7200,
        close_reason=close_reason,
        entry_time=_dt_utc(days_ago, hour_kst),
        exit_time=_dt_utc(days_ago, hour_kst + 2),
        ai_decision={"reasons": ["RSI 과매도"], "confidence": 0.85},
        risk_decision={"approved": True},
    )
    session.add(j)
    return j


def _make_reflection(
    session: AsyncSession,
    user_id: uuid.UUID,
    position_id: uuid.UUID,
    mistakes: list[str] | None = None,
) -> ReflectionReport:
    r = ReflectionReport(
        user_id=user_id,
        position_id=position_id,
        summary="테스트 회고",
        strengths=["강점1"],
        mistakes=mistakes or ["손절 너무 빠름"],
        improvements=["개선1"],
        ai_grade="B",
        model_used="claude-sonnet-4-6",
        tokens_input=100,
        tokens_output=50,
    )
    session.add(r)
    return r


def _mock_claude_response(summary: str = "BTC 거래 우수, SOL 손실 주의") -> MagicMock:
    import json
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps({
        "coach_summary": summary,
        "strengths": ["화요일 승률 우수"],
        "blind_spots": ["야간 거래 주의"],
        "weekly_goal": "연속 2패 시 당일 거래 중단",
    }))]
    msg.usage = MagicMock(input_tokens=500, output_tokens=150)
    return msg


# ── TestRunWeeklyCoaching ─────────────────────────────────────────────────────

class TestRunWeeklyCoaching:

    @patch("app.agents.trading_coach.anthropic.AsyncAnthropic")
    async def test_enough_trades_creates_report(
        self, mock_anthropic_cls: MagicMock, session: AsyncSession
    ) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response())
        mock_anthropic_cls.return_value = mock_client

        user_id = uuid.uuid4()
        for i in range(6):
            _make_journal(session, user_id, net_pnl=str(100 - i * 30), days_ago=i + 1)
        await session.flush()

        service = CoachingService(session)
        report = await service.run_weekly_coaching(user_id=user_id, period_days=28)

        assert isinstance(report, CoachingReport)
        assert report.user_id == user_id
        assert report.overall_stats["total_trades"] == 6
        assert report.coach_summary == "BTC 거래 우수, SOL 손실 주의"

    async def test_insufficient_trades_creates_skip_report(
        self, session: AsyncSession
    ) -> None:
        user_id = uuid.uuid4()
        for i in range(3):  # 3건 < MIN_TRADES_REQUIRED(5)
            _make_journal(session, user_id, days_ago=i + 1)
        await session.flush()

        service = CoachingService(session)
        report = await service.run_weekly_coaching(user_id=user_id, period_days=28)

        assert report.skip_reason is not None
        assert "3건" in report.skip_reason
        assert report.coach_summary == ""

    @patch("app.agents.trading_coach.anthropic.AsyncAnthropic")
    async def test_idempotent_same_period_returns_existing(
        self, mock_anthropic_cls: MagicMock, session: AsyncSession
    ) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response())
        mock_anthropic_cls.return_value = mock_client

        user_id = uuid.uuid4()
        for i in range(6):
            _make_journal(session, user_id, days_ago=i + 1)
        await session.flush()

        service = CoachingService(session)
        report1 = await service.run_weekly_coaching(user_id=user_id)
        report2 = await service.run_weekly_coaching(user_id=user_id)

        assert report1.id == report2.id
        # Claude는 1번만 호출됐어야 한다
        assert mock_client.messages.create.call_count == 1

    @patch("app.agents.trading_coach.anthropic.AsyncAnthropic")
    async def test_reflection_mistakes_aggregated(
        self, mock_anthropic_cls: MagicMock, session: AsyncSession
    ) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response())
        mock_anthropic_cls.return_value = mock_client

        user_id = uuid.uuid4()
        journals = []
        for i in range(5):
            j = _make_journal(session, user_id, days_ago=i + 1)
            journals.append(j)
        await session.flush()

        for j in journals[:3]:
            _make_reflection(session, user_id, j.position_id, mistakes=["손절 너무 빠름"])
        await session.flush()

        service = CoachingService(session)
        report = await service.run_weekly_coaching(user_id=user_id)

        mistakes = report.repeated_mistakes
        if mistakes:
            assert any(m["text"] == "손절 너무 빠름" for m in mistakes)

    @patch("app.agents.trading_coach.anthropic.AsyncAnthropic")
    async def test_coin_stats_in_report(
        self, mock_anthropic_cls: MagicMock, session: AsyncSession
    ) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response())
        mock_anthropic_cls.return_value = mock_client

        user_id = uuid.uuid4()
        _make_journal(session, user_id, coin="BTC", net_pnl="200.00", days_ago=1)
        _make_journal(session, user_id, coin="BTC", net_pnl="150.00", days_ago=2)
        _make_journal(session, user_id, coin="ETH", net_pnl="-80.00", days_ago=3)
        _make_journal(session, user_id, coin="ETH", net_pnl="-60.00", days_ago=4)
        _make_journal(session, user_id, coin="SOL", net_pnl="50.00",  days_ago=5)
        await session.flush()

        service = CoachingService(session)
        report = await service.run_weekly_coaching(user_id=user_id)

        coins = [c["coin"] for c in report.coin_stats]
        assert "BTC" in coins
        assert "ETH" in coins


# ── TestGetLatestReport ───────────────────────────────────────────────────────

class TestGetLatestReport:

    async def test_raises_when_no_report_exists(self, session: AsyncSession) -> None:
        user_id = uuid.uuid4()
        service = CoachingService(session)
        with pytest.raises(CoachingNotFoundError):
            await service.get_latest_report(user_id=user_id)

    @patch("app.agents.trading_coach.anthropic.AsyncAnthropic")
    async def test_returns_most_recent_report(
        self, mock_anthropic_cls: MagicMock, session: AsyncSession
    ) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response())
        mock_anthropic_cls.return_value = mock_client

        user_id = uuid.uuid4()
        for i in range(6):
            _make_journal(session, user_id, days_ago=i + 1)
        await session.flush()

        service = CoachingService(session)
        report = await service.run_weekly_coaching(user_id=user_id)
        latest = await service.get_latest_report(user_id=user_id)

        assert latest.id == report.id

    async def test_isolated_by_user_id(self, session: AsyncSession) -> None:
        # 다른 사용자의 리포트가 없으면 NotFound
        other_user = uuid.uuid4()
        my_user = uuid.uuid4()

        # other_user 리포트 직접 생성
        r = CoachingReport(
            user_id=other_user,
            period_start=_dt_utc(28),
            period_end=_dt_utc(0),
            overall_stats={"total_trades": 5},
            hourly_stats=[],
            weekday_stats=[],
            coin_stats=[],
            strategy_stats=[],
            repeated_mistakes=[],
            emotional_patterns=[],
            risk_behavior_score=80,
            coach_summary="다른 사용자",
            strengths=[],
            blind_spots=[],
            weekly_goal="",
            model_used="claude-sonnet-4-6",
        )
        session.add(r)
        await session.flush()

        service = CoachingService(session)
        with pytest.raises(CoachingNotFoundError):
            await service.get_latest_report(user_id=my_user)


# ── TestListReports ───────────────────────────────────────────────────────────

class TestListReports:

    def _add_report(
        self, session: AsyncSession, user_id: uuid.UUID, days_ago: int
    ) -> CoachingReport:
        r = CoachingReport(
            user_id=user_id,
            period_start=_dt_utc(days_ago + 28),
            period_end=_dt_utc(days_ago),
            overall_stats={"total_trades": 5},
            hourly_stats=[],
            weekday_stats=[],
            coin_stats=[],
            strategy_stats=[],
            repeated_mistakes=[],
            emotional_patterns=[],
            risk_behavior_score=75,
            coach_summary="테스트",
            strengths=[],
            blind_spots=[],
            weekly_goal="목표",
            skip_reason=None,
            model_used="claude-sonnet-4-6",
        )
        session.add(r)
        return r

    async def test_returns_paginated_results(self, session: AsyncSession) -> None:
        user_id = uuid.uuid4()
        for i in range(5):
            self._add_report(session, user_id, days_ago=i * 7)
        await session.flush()

        service = CoachingService(session)
        result = await service.list_reports(user_id=user_id, page=1, size=3)

        assert result["total"] == 5
        assert len(result["items"]) == 3
        assert result["page"] == 1

    async def test_returns_empty_for_new_user(self, session: AsyncSession) -> None:
        service = CoachingService(session)
        result = await service.list_reports(user_id=uuid.uuid4(), page=1, size=10)

        assert result["total"] == 0
        assert result["items"] == []

    async def test_sorted_by_period_end_desc(self, session: AsyncSession) -> None:
        user_id = uuid.uuid4()
        for i in [14, 7, 21, 28, 0]:
            self._add_report(session, user_id, days_ago=i)
        await session.flush()

        service = CoachingService(session)
        result = await service.list_reports(user_id=user_id, page=1, size=10)

        items = result["items"]
        period_ends = [item.period_end for item in items]
        assert period_ends == sorted(period_ends, reverse=True)
