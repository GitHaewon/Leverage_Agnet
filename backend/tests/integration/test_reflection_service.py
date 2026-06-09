"""
ReflectionService 통합 테스트.

실제 DB 세션(SQLite in-memory)과 Mock Claude API를 사용한다.
검증 대상:
  - run_and_save() — DB에 레코드 생성
  - 멱등성 — 동일 position_id 중복 생성 방지
  - get_by_position() — 조회 및 404 처리
  - list_reports() — 페이지네이션
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.reflection_report import ReflectionReport
from app.schemas.reflection import ReflectionInput
from app.services.reflection_service import ReflectionNotFoundError, ReflectionService


# ── 테스트 DB 설정 (SQLite async in-memory) ───────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        # SQLite는 JSON 컬럼 타입이 없으므로 TEXT로 처리 — 통합 테스트 범위 내에서 허용
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncSession:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
def valid_input() -> ReflectionInput:
    return ReflectionInput(
        position_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        coin="BTC",
        symbol="BTCUSDT",
        direction="LONG",
        leverage=5,
        user_max_leverage=10,
        entry_price=Decimal("67450.00"),
        close_price=Decimal("69200.00"),
        stop_loss=Decimal("66800.00"),
        take_profit=Decimal("69200.00"),
        net_pnl=Decimal("131.50"),
        pnl_percentage=Decimal("13.15"),
        duration_seconds=10800,
        close_reason="tp_hit",
        signal_confidence=0.87,
        signal_reasons=["RSI 42.3 과매도 진입"],
        signal_rr_ratio=2.71,
    )


def _mock_claude_response(grade: str = "B") -> MagicMock:
    """Claude API 응답 Mock."""
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps({
        "summary": "BTC LONG 포지션 목표가 달성",
        "strengths": ["RSI 과매도 진입 정확", "Funding Rate 역발상 성공"],
        "mistakes": ["TP 설정 소폭 보수적"],
        "improvements": ["부분 익절 전략 도입 검토"],
        "entry_analysis": "RSI 42.3에서 EMA200 지지선 반등 진입 — 기술적으로 우수",
        "pnl_cause": "기술적 과매도 반등과 숏 스퀴즈 복합 효과",
        "ai_grade": grade,
    }))]
    msg.usage = MagicMock(input_tokens=600, output_tokens=180)
    return msg


# ── run_and_save() 테스트 ─────────────────────────────────────────────────────

class TestRunAndSave:

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_creates_reflection_report(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
        valid_input: ReflectionInput,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response("A")

        service = ReflectionService(db_session)
        report = await service.run_and_save(valid_input)

        assert report.id is not None
        assert report.position_id == valid_input.position_id
        assert report.user_id == valid_input.user_id
        assert report.summary == "BTC LONG 포지션 목표가 달성"
        assert report.ai_grade == "A"
        assert isinstance(report.strengths, list)
        assert isinstance(report.mistakes, list)
        assert isinstance(report.improvements, list)
        assert report.model_used == "claude-sonnet-4-6"

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_idempotent_on_duplicate_position(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
        valid_input: ReflectionInput,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response()

        service = ReflectionService(db_session)

        first = await service.run_and_save(valid_input)
        second = await service.run_and_save(valid_input)

        assert first.id == second.id
        # Claude API는 한 번만 호출되어야 함
        assert mock_client.messages.create.call_count == 1

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_saves_risk_violations_when_present(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response("D")

        inp = ReflectionInput(
            position_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            coin="ETH",
            symbol="ETHUSDT",
            direction="SHORT",
            leverage=15,
            user_max_leverage=10,  # 위반
            entry_price=Decimal("3500.00"),
            close_price=Decimal("3600.00"),
            stop_loss=Decimal("3550.00"),
            net_pnl=Decimal("-50.00"),
            pnl_percentage=Decimal("-5.00"),
            duration_seconds=600,
            close_reason="sl_hit",
            signal_rr_ratio=1.2,  # 위반
        )

        service = ReflectionService(db_session)
        report = await service.run_and_save(inp)

        assert len(report.risk_rule_violations) >= 2

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_saves_trade_context_snapshot(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
        valid_input: ReflectionInput,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response()

        service = ReflectionService(db_session)
        report = await service.run_and_save(valid_input)

        assert report.trade_context is not None
        assert report.trade_context["coin"] == "BTC"
        assert report.trade_context["direction"] == "LONG"
        assert report.trade_context["leverage"] == 5

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_saves_token_counts(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
        valid_input: ReflectionInput,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response()

        service = ReflectionService(db_session)
        report = await service.run_and_save(valid_input)

        assert report.tokens_input == 600
        assert report.tokens_output == 180


# ── get_by_position() 테스트 ──────────────────────────────────────────────────

class TestGetByPosition:

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_returns_report_for_valid_position(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
        valid_input: ReflectionInput,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response()

        service = ReflectionService(db_session)
        await service.run_and_save(valid_input)

        response = await service.get_by_position(
            valid_input.position_id, valid_input.user_id
        )

        assert response.position_id == valid_input.position_id
        assert response.summary == "BTC LONG 포지션 목표가 달성"

    async def test_raises_not_found_for_missing_position(
        self,
        db_session: AsyncSession,
    ) -> None:
        service = ReflectionService(db_session)

        with pytest.raises(ReflectionNotFoundError):
            await service.get_by_position(uuid.uuid4(), uuid.uuid4())

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_raises_not_found_for_wrong_user(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
        valid_input: ReflectionInput,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response()

        service = ReflectionService(db_session)
        await service.run_and_save(valid_input)

        wrong_user = uuid.uuid4()
        with pytest.raises(ReflectionNotFoundError):
            await service.get_by_position(valid_input.position_id, wrong_user)


# ── list_reports() 테스트 ─────────────────────────────────────────────────────

class TestListReports:

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_returns_paginated_list(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response()

        user_id = uuid.uuid4()
        service = ReflectionService(db_session)

        # 3개 생성
        for _ in range(3):
            inp = ReflectionInput(
                position_id=uuid.uuid4(),
                user_id=user_id,
                coin="BTC",
                symbol="BTCUSDT",
                direction="LONG",
                leverage=5,
                entry_price=Decimal("67000.00"),
                close_price=Decimal("68000.00"),
                stop_loss=Decimal("66000.00"),
                net_pnl=Decimal("100.00"),
                pnl_percentage=Decimal("10.00"),
                duration_seconds=3600,
                close_reason="tp_hit",
            )
            await service.run_and_save(inp)

        result = await service.list_reports(user_id, page=1, size=10)

        assert result["total"] == 3
        assert len(result["items"]) == 3
        assert result["page"] == 1
        assert result["pages"] == 1

    async def test_returns_empty_for_new_user(
        self,
        db_session: AsyncSession,
    ) -> None:
        service = ReflectionService(db_session)
        result = await service.list_reports(uuid.uuid4(), page=1, size=20)

        assert result["total"] == 0
        assert result["items"] == []

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    async def test_pagination_works_correctly(
        self,
        mock_anthropic_cls: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response()

        user_id = uuid.uuid4()
        service = ReflectionService(db_session)

        # 5개 생성
        for _ in range(5):
            inp = ReflectionInput(
                position_id=uuid.uuid4(),
                user_id=user_id,
                coin="BTC",
                symbol="BTCUSDT",
                direction="LONG",
                leverage=5,
                entry_price=Decimal("67000.00"),
                close_price=Decimal("68000.00"),
                stop_loss=Decimal("66000.00"),
                net_pnl=Decimal("100.00"),
                pnl_percentage=Decimal("10.00"),
                duration_seconds=3600,
                close_reason="tp_hit",
            )
            await service.run_and_save(inp)

        page1 = await service.list_reports(user_id, page=1, size=3)
        page2 = await service.list_reports(user_id, page=2, size=3)

        assert page1["total"] == 5
        assert len(page1["items"]) == 3
        assert len(page2["items"]) == 2
        assert page1["pages"] == 2
