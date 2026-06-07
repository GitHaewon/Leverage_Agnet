"""
TradeJournalRepository 단위 테스트.

SQLAlchemy 2.0.36 + Python 3.14 호환 문제를 sys.modules 스텁으로 우회한다.
ORM 모델을 MagicMock으로 교체하고 AsyncSession만 AsyncMock으로 구성한다.

검증 항목:
  - create: add/flush/refresh 호출
  - get_by_id / get_by_position_id: 결과 반환 / None
  - list_by_user: journals + total 반환
  - search: 필터 없는 기본 실행
  - update_notes: 값 변경 / None 반환
"""
from __future__ import annotations

import sys
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

# ── SQLAlchemy ORM 우회 설정 ────────────────────────────────────────────────────

_backend = Path(__file__).parents[3] / "backend"

_enums_spec = importlib.util.spec_from_file_location(
    "app.models.enums",
    _backend / "app" / "models" / "enums.py",
)
_enums_mod = importlib.util.module_from_spec(_enums_spec)
sys.modules["app.models.enums"] = _enums_mod
_enums_spec.loader.exec_module(_enums_mod)

if "app.models" not in sys.modules:
    _ms = MagicMock()
    _ms.enums = _enums_mod
    sys.modules["app.models"] = _ms

for _n in [
    "app.models.base", "app.models.trade_journal", "app.models.user",
    "app.models.position", "app.models.signal", "app.models.trade_log",
]:
    sys.modules.setdefault(_n, MagicMock())

# 다른 테스트 파일이 이미 이 모듈을 MagicMock으로 등록했을 수 있으므로 제거한다.
# (sys.modules는 pytest 세션 전체에서 공유되기 때문)
sys.modules.pop("app.repositories.trade_journal_repository", None)

# ── 이제 안전하게 import ────────────────────────────────────────────────────────

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.repositories.trade_journal_repository import TradeJournalRepository
from app.schemas.trade_journal import JournalSearchParams, TradeJournalCreate
from app.models.enums import CloseReasonType, SignalDirectionType

# SQLAlchemy 쿼리 생성 함수를 패치한다.
# select(TradeJournal) 은 MagicMock TradeJournal을 거부하므로, 체이닝 가능한 Mock으로 교체.
import app.repositories.trade_journal_repository as _repo_mod
_repo_mod.select = MagicMock(side_effect=lambda *a, **kw: MagicMock())
_repo_mod.func = MagicMock()
_repo_mod.and_ = MagicMock(return_value=MagicMock())
_repo_mod.or_ = MagicMock(return_value=MagicMock())


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _make_repo() -> tuple[TradeJournalRepository, AsyncMock]:
    db = AsyncMock()
    return TradeJournalRepository(db), db


def _make_create_data(**kwargs) -> TradeJournalCreate:
    defaults = dict(
        trade_log_id=uuid.uuid4(), position_id=uuid.uuid4(),
        user_id=uuid.uuid4(), signal_id=None,
        entry_time=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        exit_time=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
        symbol="BTCUSDT", coin="BTC",
        direction=SignalDirectionType.LONG, leverage=5, is_ai_trade=True,
        strategy="RSI_OVERSOLD", ai_decision=None, risk_decision=None,
        entry_reason="• RSI 과매도", exit_reason="익절",
        net_pnl=Decimal("200"), pnl_percentage=Decimal("10"),
        duration_seconds=3600, close_reason=CloseReasonType.TP_HIT,
        user_notes=None,
    )
    defaults.update(kwargs)
    return TradeJournalCreate(**defaults)


def _scalar_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.scalar_one.return_value = value
    r.scalars.return_value.all.return_value = value if isinstance(value, list) else [value]
    r.one.return_value = MagicMock(
        total=0, wins=0, total_pnl=Decimal("0"),
        avg_pnl=None, best_pnl=None, worst_pnl=None,
        avg_duration=None, max_duration=None, min_duration=None,
    )
    r.all.return_value = []
    return r


# ── create ────────────────────────────────────────────────────────────────────

class TestCreate:
    @pytest.mark.asyncio
    async def test_adds_to_session(self) -> None:
        repo, db = _make_repo()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        journal_mock = MagicMock()

        with patch("app.repositories.trade_journal_repository.TradeJournal",
                   return_value=journal_mock):
            await repo.create(_make_create_data())

        db.add.assert_called_once_with(journal_mock)

    @pytest.mark.asyncio
    async def test_flushes_and_refreshes(self) -> None:
        repo, db = _make_repo()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        journal_mock = MagicMock()

        with patch("app.repositories.trade_journal_repository.TradeJournal",
                   return_value=journal_mock):
            await repo.create(_make_create_data())

        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(journal_mock)

    @pytest.mark.asyncio
    async def test_returns_journal(self) -> None:
        repo, db = _make_repo()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        journal_mock = MagicMock()
        journal_mock.id = uuid.uuid4()

        with patch("app.repositories.trade_journal_repository.TradeJournal",
                   return_value=journal_mock):
            result = await repo.create(_make_create_data())

        assert result is journal_mock


# ── get_by_id ─────────────────────────────────────────────────────────────────

class TestGetById:
    @pytest.mark.asyncio
    async def test_returns_journal(self) -> None:
        repo, db = _make_repo()
        journal = MagicMock()
        db.execute = AsyncMock(return_value=_scalar_result(journal))

        result = await repo.get_by_id(uuid.uuid4(), uuid.uuid4())
        assert result is journal

    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        repo, db = _make_repo()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.get_by_id(uuid.uuid4(), uuid.uuid4())
        assert result is None


# ── get_by_position_id ────────────────────────────────────────────────────────

class TestGetByPositionId:
    @pytest.mark.asyncio
    async def test_returns_journal(self) -> None:
        repo, db = _make_repo()
        journal = MagicMock()
        db.execute = AsyncMock(return_value=_scalar_result(journal))

        result = await repo.get_by_position_id(uuid.uuid4())
        assert result is journal

    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        repo, db = _make_repo()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.get_by_position_id(uuid.uuid4())
        assert result is None


# ── list_by_user ──────────────────────────────────────────────────────────────

class TestListByUser:
    @pytest.mark.asyncio
    async def test_returns_journals_and_total(self) -> None:
        repo, db = _make_repo()
        journals = [MagicMock(), MagicMock()]

        count_r = MagicMock()
        count_r.scalar_one.return_value = 2
        list_r = MagicMock()
        list_r.scalars.return_value.all.return_value = journals
        db.execute = AsyncMock(side_effect=[count_r, list_r])

        result_list, total = await repo.list_by_user(uuid.uuid4(), page=1, size=20)
        assert total == 2
        assert len(result_list) == 2

    @pytest.mark.asyncio
    async def test_empty(self) -> None:
        repo, db = _make_repo()
        count_r = MagicMock()
        count_r.scalar_one.return_value = 0
        list_r = MagicMock()
        list_r.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_r, list_r])

        result_list, total = await repo.list_by_user(uuid.uuid4())
        assert total == 0
        assert result_list == []

    @pytest.mark.asyncio
    async def test_calls_execute_twice(self) -> None:
        """count 쿼리 + data 쿼리 = execute 2회."""
        repo, db = _make_repo()
        count_r = MagicMock()
        count_r.scalar_one.return_value = 0
        list_r = MagicMock()
        list_r.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_r, list_r])

        await repo.list_by_user(uuid.uuid4())
        assert db.execute.call_count == 2


# ── search ────────────────────────────────────────────────────────────────────

class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        repo, db = _make_repo()
        count_r = MagicMock()
        count_r.scalar_one.return_value = 3
        list_r = MagicMock()
        list_r.scalars.return_value.all.return_value = [MagicMock() for _ in range(3)]
        db.execute = AsyncMock(side_effect=[count_r, list_r])

        params = JournalSearchParams(page=1, size=10)
        journals, total = await repo.search(uuid.uuid4(), params)
        assert total == 3
        assert len(journals) == 3

    @pytest.mark.asyncio
    async def test_calls_execute_twice(self) -> None:
        repo, db = _make_repo()
        count_r = MagicMock()
        count_r.scalar_one.return_value = 0
        list_r = MagicMock()
        list_r.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_r, list_r])

        params = JournalSearchParams(coin="BTC", page=1, size=10)
        await repo.search(uuid.uuid4(), params)
        assert db.execute.call_count == 2


# ── update_notes ──────────────────────────────────────────────────────────────

class TestUpdateNotes:
    @pytest.mark.asyncio
    async def test_updates_and_returns(self) -> None:
        repo, db = _make_repo()
        journal = MagicMock()
        journal.user_notes = None
        db.execute = AsyncMock(return_value=_scalar_result(journal))
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await repo.update_notes(uuid.uuid4(), uuid.uuid4(), "새 메모")
        assert result is journal
        assert journal.user_notes == "새 메모"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        repo, db = _make_repo()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.update_notes(uuid.uuid4(), uuid.uuid4(), "메모")
        assert result is None
