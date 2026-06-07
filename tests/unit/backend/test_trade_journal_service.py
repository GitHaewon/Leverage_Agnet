"""
TradeJournalService 단위 테스트.

주의: SQLAlchemy 2.0.36 + Python 3.14 호환 문제로 ORM 모델을 직접 import하면
TypeError가 발생한다. 이 파일은 sys.modules 스텁으로 ORM 체인을 우회한다.

검증 항목:
  - _extract_strategy (signals_fired / signals / reasons 우선순위)
  - _build_entry_reason (bullet point 조합)
  - _build_exit_reason (한국어 레이블)
  - create_from_closed_position (정상 생성 / 멱등성 / AI 데이터 없음)
  - list_journals 페이지 계산
  - get_journal 404 처리
  - update_notes 정상 / 404 처리
  - get_stats 위임
"""
from __future__ import annotations

import sys
import importlib.util
import os
from pathlib import Path
from unittest.mock import MagicMock

# ── SQLAlchemy ORM 우회 설정 ────────────────────────────────────────────────────
# SQLAlchemy 2.0.36 이 Python 3.14 에서 Union.__getitem__ 로 실패함.
# ORM 모델 import 체인을 sys.modules 스텁으로 차단한다.

_backend = Path(__file__).parents[3] / "backend"

# 1) app.models.enums 를 __init__.py 없이 직접 로드
_enums_spec = importlib.util.spec_from_file_location(
    "app.models.enums",
    _backend / "app" / "models" / "enums.py",
)
_enums_mod = importlib.util.module_from_spec(_enums_spec)
sys.modules["app.models.enums"] = _enums_mod
_enums_spec.loader.exec_module(_enums_mod)

# 2) app.models 패키지를 MagicMock 으로 스텁 (ORM __init__ 실행 방지)
if "app.models" not in sys.modules:
    _models_stub = MagicMock()
    _models_stub.enums = _enums_mod
    sys.modules["app.models"] = _models_stub

# 3) ORM 모델 모듈 스텁
for _n in [
    "app.models.base", "app.models.trade_journal", "app.models.user",
    "app.models.position", "app.models.signal", "app.models.trade_log",
]:
    sys.modules.setdefault(_n, MagicMock())

# 4) Repository 스텁 (실제 DB 쿼리 불필요)
sys.modules.setdefault("app.repositories.trade_journal_repository", MagicMock())

# ── 이제 안전하게 import ────────────────────────────────────────────────────────

import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.trade_journal_service import (
    JournalNotFoundError,
    TradeJournalService,
    _build_entry_reason,
    _build_exit_reason,
    _extract_strategy,
)
from app.schemas.trade_journal import (
    JournalSearchParams,
    JournalStatsResponse,
    PnLBreakdown,
    TradeJournalListResponse,
    TradeJournalResponse,
    TradeJournalUpdate,
)
from app.models.enums import CloseReasonType, SignalDirectionType


# ── 픽스처 ────────────────────────────────────────────────────────────────────

def _make_journal(**kwargs) -> MagicMock:
    j = MagicMock()
    j.id = uuid.uuid4()
    j.trade_log_id = uuid.uuid4()
    j.position_id = uuid.uuid4()
    j.user_id = uuid.uuid4()
    j.signal_id = None
    j.entry_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    j.exit_time = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    j.symbol = "BTCUSDT"
    j.coin = "BTC"
    j.direction = SignalDirectionType.LONG
    j.leverage = 5
    j.is_ai_trade = True
    j.strategy = "RSI_OVERSOLD + EMA200_SUPPORT"
    j.ai_decision = {"direction": "LONG", "confidence": 0.87}
    j.risk_decision = {"approved": True, "final_leverage": 5}
    j.entry_reason = "• RSI 과매도\n• EMA200 지지"
    j.exit_reason = "익절 (Take Profit 도달)"
    j.net_pnl = Decimal("234.5")
    j.pnl_percentage = Decimal("12.3")
    j.duration_seconds = 3600
    j.close_reason = CloseReasonType.TP_HIT
    j.user_notes = None
    j.created_at = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    j.updated_at = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    for k, v in kwargs.items():
        setattr(j, k, v)
    return j


def _make_service() -> tuple[TradeJournalService, MagicMock]:
    db = AsyncMock()
    service = TradeJournalService(db)
    mock_repo = MagicMock()
    service._repo = mock_repo
    return service, mock_repo


def _make_response(j: MagicMock) -> TradeJournalResponse:
    return TradeJournalResponse(
        id=j.id, trade_log_id=j.trade_log_id, position_id=j.position_id,
        user_id=j.user_id, signal_id=j.signal_id,
        entry_time=j.entry_time, exit_time=j.exit_time,
        symbol=j.symbol, coin=j.coin, direction=j.direction,
        leverage=j.leverage, is_ai_trade=j.is_ai_trade,
        strategy=j.strategy, ai_decision=j.ai_decision,
        risk_decision=j.risk_decision, entry_reason=j.entry_reason,
        exit_reason=j.exit_reason, net_pnl=j.net_pnl,
        pnl_percentage=j.pnl_percentage, duration_seconds=j.duration_seconds,
        close_reason=j.close_reason, user_notes=j.user_notes,
        created_at=j.created_at, updated_at=j.updated_at,
    )


def _make_stats() -> JournalStatsResponse:
    bd = PnLBreakdown(label="LONG", count=0, win_count=0, loss_count=0, total_pnl=Decimal("0"), win_rate=0.0)
    return JournalStatsResponse(
        from_date=None, to_date=None, total_trades=10, win_trades=6, loss_trades=4,
        win_rate=0.6, total_net_pnl=Decimal("1000"), total_fees=Decimal("20"),
        avg_net_pnl=Decimal("100"), best_trade_pnl=Decimal("500"),
        worst_trade_pnl=Decimal("-200"), avg_duration_seconds=3600.0,
        longest_trade_seconds=7200, shortest_trade_seconds=300,
        long_breakdown=bd, short_breakdown=bd, close_reason_breakdown=[], top_coins=[],
    )


_BASE_KWARGS = dict(
    position_id=uuid.uuid4(), user_id=uuid.uuid4(), trade_log_id=uuid.uuid4(),
    signal_id=None, symbol="BTCUSDT", coin="BTC", direction="LONG",
    leverage=5, is_ai_trade=True, entry_price=Decimal("67000"),
    close_price=Decimal("69000"),
    opened_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
    closed_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
    duration_seconds=3600, close_reason="tp_hit",
    net_pnl=Decimal("200"), pnl_percentage=Decimal("10"),
)


# ── 순수 헬퍼 함수 ────────────────────────────────────────────────────────────

class TestExtractStrategy:
    def test_uses_signals_fired_first(self) -> None:
        data = {"signals_fired": ["rsi_oversold", "ema200_support"]}
        assert _extract_strategy(data) == "RSI_OVERSOLD + EMA200_SUPPORT"

    def test_falls_back_to_signals_key(self) -> None:
        data = {"signals": ["MACD_CROSS"]}
        assert _extract_strategy(data) == "MACD_CROSS"

    def test_falls_back_to_reasons(self) -> None:
        data = {"reasons": ["RSI 42 과매도 구간 진입"]}
        result = _extract_strategy(data)
        assert result is not None
        assert len(result) > 0

    def test_returns_none_when_empty(self) -> None:
        assert _extract_strategy(None) is None
        assert _extract_strategy({}) is None

    def test_limits_to_three_signals(self) -> None:
        data = {"signals_fired": ["a", "b", "c", "d", "e"]}
        result = _extract_strategy(data)
        assert result.count("+") == 2  # 최대 3개 → '+' 2개

    def test_reasons_capped_at_100_chars(self) -> None:
        long_reason = "X" * 200
        data = {"reasons": [long_reason]}
        result = _extract_strategy(data)
        assert len(result) <= 100


class TestBuildEntryReason:
    def test_joins_with_bullets(self) -> None:
        result = _build_entry_reason(["RSI 과매도", "EMA200 지지"])
        assert "• RSI 과매도" in result
        assert "• EMA200 지지" in result

    def test_none_when_empty_list(self) -> None:
        assert _build_entry_reason([]) is None

    def test_none_when_none(self) -> None:
        assert _build_entry_reason(None) is None

    def test_single_reason(self) -> None:
        result = _build_entry_reason(["단일 이유"])
        assert "• 단일 이유" in result


class TestBuildExitReason:
    def test_tp_hit_returns_korean(self) -> None:
        assert "익절" in _build_exit_reason("tp_hit")

    def test_sl_hit_returns_korean(self) -> None:
        assert "손절" in _build_exit_reason("sl_hit")

    def test_manual_returns_korean(self) -> None:
        assert "수동" in _build_exit_reason("manual")

    def test_liquidated_returns_korean(self) -> None:
        assert "강제" in _build_exit_reason("liquidated")

    def test_unknown_passthrough(self) -> None:
        assert _build_exit_reason("unknown_xyz") == "unknown_xyz"


# ── create_from_closed_position ───────────────────────────────────────────────

class TestCreateFromClosedPosition:
    @pytest.mark.asyncio
    async def test_creates_new_journal(self) -> None:
        service, repo = _make_service()
        journal = _make_journal()
        repo.get_by_position_id = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=journal)

        result = await service.create_from_closed_position(**_BASE_KWARGS)
        assert result is journal
        repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotent_returns_existing(self) -> None:
        service, repo = _make_service()
        existing = _make_journal()
        repo.get_by_position_id = AsyncMock(return_value=existing)
        repo.create = AsyncMock()

        result = await service.create_from_closed_position(**_BASE_KWARGS)
        assert result is existing
        repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_without_ai_data(self) -> None:
        service, repo = _make_service()
        journal = _make_journal()
        repo.get_by_position_id = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=journal)

        result = await service.create_from_closed_position(**_BASE_KWARGS)
        assert result is journal

    @pytest.mark.asyncio
    async def test_signal_reasons_in_create_data(self) -> None:
        service, repo = _make_service()
        journal = _make_journal()
        repo.get_by_position_id = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=journal)

        await service.create_from_closed_position(
            **_BASE_KWARGS, signal_reasons=["RSI 과매도", "EMA200 지지"]
        )
        create_data = repo.create.call_args[0][0]
        assert "RSI 과매도" in create_data.entry_reason

    @pytest.mark.asyncio
    async def test_exit_reason_is_korean(self) -> None:
        service, repo = _make_service()
        journal = _make_journal()
        repo.get_by_position_id = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=journal)

        await service.create_from_closed_position(**_BASE_KWARGS)
        create_data = repo.create.call_args[0][0]
        assert "익절" in create_data.exit_reason


# ── list_journals ─────────────────────────────────────────────────────────────

class TestListJournals:
    @pytest.mark.asyncio
    async def test_returns_list_response(self) -> None:
        service, repo = _make_service()
        journals = [_make_journal(), _make_journal()]
        repo.list_by_user = AsyncMock(return_value=(journals, 2))

        with patch("app.services.trade_journal_service.TradeJournalResponse.model_validate",
                   side_effect=_make_response):
            result = await service.list_journals(uuid.uuid4(), page=1, size=20)

        assert result.total == 2
        assert result.pages == 1

    @pytest.mark.asyncio
    async def test_pages_calculation(self) -> None:
        service, repo = _make_service()
        repo.list_by_user = AsyncMock(return_value=([], 45))

        with patch("app.services.trade_journal_service.TradeJournalResponse.model_validate",
                   side_effect=_make_response):
            result = await service.list_journals(uuid.uuid4(), page=1, size=20)

        assert result.pages == 3  # ceil(45/20)

    @pytest.mark.asyncio
    async def test_empty_returns_pages_one(self) -> None:
        service, repo = _make_service()
        repo.list_by_user = AsyncMock(return_value=([], 0))

        with patch("app.services.trade_journal_service.TradeJournalResponse.model_validate",
                   side_effect=_make_response):
            result = await service.list_journals(uuid.uuid4(), page=1, size=20)

        assert result.pages == 1


# ── get_journal ───────────────────────────────────────────────────────────────

class TestGetJournal:
    @pytest.mark.asyncio
    async def test_returns_response(self) -> None:
        service, repo = _make_service()
        journal = _make_journal()
        repo.get_by_id = AsyncMock(return_value=journal)

        with patch("app.services.trade_journal_service.TradeJournalResponse.model_validate",
                   return_value=_make_response(journal)):
            result = await service.get_journal(journal.id, journal.user_id)

        assert result.id == journal.id

    @pytest.mark.asyncio
    async def test_raises_not_found(self) -> None:
        service, repo = _make_service()
        repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(JournalNotFoundError):
            await service.get_journal(uuid.uuid4(), uuid.uuid4())


# ── update_notes ──────────────────────────────────────────────────────────────

class TestUpdateNotes:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        service, repo = _make_service()
        journal = _make_journal(user_notes="새 메모")
        repo.update_notes = AsyncMock(return_value=journal)

        with patch("app.services.trade_journal_service.TradeJournalResponse.model_validate",
                   return_value=_make_response(journal)):
            result = await service.update_notes(
                journal.id, journal.user_id, TradeJournalUpdate(user_notes="새 메모")
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_raises_not_found(self) -> None:
        service, repo = _make_service()
        repo.update_notes = AsyncMock(return_value=None)

        with pytest.raises(JournalNotFoundError):
            await service.update_notes(
                uuid.uuid4(), uuid.uuid4(), TradeJournalUpdate(user_notes="x")
            )

    @pytest.mark.asyncio
    async def test_clears_notes(self) -> None:
        service, repo = _make_service()
        journal = _make_journal(user_notes=None)
        repo.update_notes = AsyncMock(return_value=journal)

        with patch("app.services.trade_journal_service.TradeJournalResponse.model_validate",
                   return_value=_make_response(journal)):
            await service.update_notes(
                journal.id, journal.user_id, TradeJournalUpdate(user_notes=None)
            )

        called_with_none = repo.update_notes.call_args[0][2]
        assert called_with_none is None


# ── get_stats ─────────────────────────────────────────────────────────────────

class TestGetStats:
    @pytest.mark.asyncio
    async def test_delegates_to_repo(self) -> None:
        service, repo = _make_service()
        stats = _make_stats()
        repo.get_stats = AsyncMock(return_value=stats)

        result = await service.get_stats(uuid.uuid4())
        assert result is stats

    @pytest.mark.asyncio
    async def test_passes_date_range(self) -> None:
        service, repo = _make_service()
        repo.get_stats = AsyncMock(return_value=_make_stats())

        from_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        to_date = datetime(2026, 6, 8, tzinfo=timezone.utc)
        await service.get_stats(uuid.uuid4(), from_date=from_date, to_date=to_date)

        call_args = repo.get_stats.call_args
        assert from_date in call_args[0] or call_args[1].get("from_date") == from_date
