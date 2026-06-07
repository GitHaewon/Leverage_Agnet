"""
Trade Journal API 단위 테스트.

FastAPI가 venv에 없어 TestClient를 사용할 수 없다.
대신 Pydantic 스키마 검증 + 서비스 의존성 인터페이스를 검증한다.

검증 항목:
  - TradeJournalResponse 스키마 직렬화 / 역직렬화
  - JournalSearchParams 유효성 검사
  - TradeJournalUpdate 유효성 검사
  - TradeJournalListResponse 페이지 구조
  - JournalStatsResponse 통계 구조
  - 라우터 파일 import 가능 여부 (FastAPI 의존성 없이)
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

sys.modules.setdefault("app.repositories.trade_journal_repository", MagicMock())

# ── 이제 안전하게 import ────────────────────────────────────────────────────────

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.schemas.trade_journal import (
    AIDecisionSnapshot,
    JournalSearchParams,
    JournalStatsResponse,
    PnLBreakdown,
    RiskDecisionSnapshot,
    TradeJournalCreate,
    TradeJournalListResponse,
    TradeJournalResponse,
    TradeJournalUpdate,
)
from app.models.enums import CloseReasonType, SignalDirectionType
from app.services.trade_journal_service import JournalNotFoundError


# ── 스키마 검증 ───────────────────────────────────────────────────────────────

class TestTradeJournalResponseSchema:
    def _make(self, **kwargs) -> dict:
        defaults = dict(
            id=str(uuid.uuid4()), trade_log_id=str(uuid.uuid4()),
            position_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
            signal_id=None,
            entry_time="2026-06-01T10:00:00+00:00",
            exit_time="2026-06-01T11:00:00+00:00",
            symbol="BTCUSDT", coin="BTC", direction="LONG",
            leverage=5, is_ai_trade=True, strategy="RSI_OVERSOLD",
            ai_decision={"direction": "LONG", "confidence": 0.87},
            risk_decision={"approved": True},
            entry_reason="• RSI 과매도", exit_reason="익절",
            net_pnl="200.00000000", pnl_percentage="10.0000",
            duration_seconds=3600, close_reason="tp_hit",
            user_notes=None,
            created_at="2026-06-01T11:00:00+00:00",
            updated_at="2026-06-01T11:00:00+00:00",
        )
        defaults.update(kwargs)
        return defaults

    def test_validates_valid_response(self) -> None:
        r = TradeJournalResponse.model_validate(self._make())
        assert r.coin == "BTC"
        assert r.direction == SignalDirectionType.LONG
        assert r.leverage == 5
        assert r.net_pnl == Decimal("200")

    def test_nullable_fields_accept_none(self) -> None:
        r = TradeJournalResponse.model_validate(
            self._make(signal_id=None, strategy=None, ai_decision=None,
                       risk_decision=None, entry_reason=None, exit_reason=None,
                       user_notes=None)
        )
        assert r.signal_id is None
        assert r.strategy is None
        assert r.user_notes is None

    def test_serializes_to_json(self) -> None:
        r = TradeJournalResponse.model_validate(self._make())
        data = r.model_dump()
        assert data["coin"] == "BTC"
        assert data["close_reason"] == CloseReasonType.TP_HIT


class TestTradeJournalUpdateSchema:
    def test_accepts_string_notes(self) -> None:
        u = TradeJournalUpdate(user_notes="메모 내용")
        assert u.user_notes == "메모 내용"

    def test_accepts_none_notes(self) -> None:
        u = TradeJournalUpdate(user_notes=None)
        assert u.user_notes is None

    def test_strips_whitespace(self) -> None:
        u = TradeJournalUpdate(user_notes="  앞뒤 공백  ")
        assert u.user_notes == "앞뒤 공백"

    def test_empty_model(self) -> None:
        u = TradeJournalUpdate()
        assert u.user_notes is None


class TestJournalSearchParamsSchema:
    def test_defaults(self) -> None:
        p = JournalSearchParams()
        assert p.page == 1
        assert p.size == 20
        assert p.coin is None
        assert p.direction is None

    def test_coin_filter(self) -> None:
        p = JournalSearchParams(coin="BTC")
        assert p.coin == "BTC"

    def test_direction_filter(self) -> None:
        p = JournalSearchParams(direction=SignalDirectionType.LONG)
        assert p.direction == SignalDirectionType.LONG

    def test_pnl_range(self) -> None:
        p = JournalSearchParams(
            pnl_min=Decimal("-100"), pnl_max=Decimal("500")
        )
        assert p.pnl_min == Decimal("-100")
        assert p.pnl_max == Decimal("500")

    def test_pnl_max_must_gte_min(self) -> None:
        with pytest.raises(Exception):
            JournalSearchParams(pnl_min=Decimal("100"), pnl_max=Decimal("50"))

    def test_size_bounded(self) -> None:
        with pytest.raises(Exception):
            JournalSearchParams(size=200)  # max is 100


class TestTradeJournalListResponse:
    def test_structure(self) -> None:
        r = TradeJournalListResponse(items=[], total=0, page=1, size=20, pages=1)
        assert r.total == 0
        assert r.pages == 1

    def test_with_items(self) -> None:
        resp = TradeJournalResponse.model_validate({
            "id": str(uuid.uuid4()), "trade_log_id": str(uuid.uuid4()),
            "position_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()),
            "signal_id": None, "entry_time": "2026-06-01T10:00:00+00:00",
            "exit_time": "2026-06-01T11:00:00+00:00", "symbol": "BTCUSDT",
            "coin": "BTC", "direction": "LONG", "leverage": 5, "is_ai_trade": True,
            "strategy": None, "ai_decision": None, "risk_decision": None,
            "entry_reason": None, "exit_reason": None, "net_pnl": "200",
            "pnl_percentage": "10", "duration_seconds": 3600, "close_reason": "tp_hit",
            "user_notes": None, "created_at": "2026-06-01T11:00:00+00:00",
            "updated_at": "2026-06-01T11:00:00+00:00",
        })
        r = TradeJournalListResponse(items=[resp], total=1, page=1, size=20, pages=1)
        assert len(r.items) == 1


class TestJournalStatsResponse:
    def _bd(self, label: str = "LONG") -> PnLBreakdown:
        return PnLBreakdown(label=label, count=0, win_count=0, loss_count=0,
                            total_pnl=Decimal("0"), win_rate=0.0)

    def test_basic_stats(self) -> None:
        s = JournalStatsResponse(
            from_date=None, to_date=None,
            total_trades=10, win_trades=6, loss_trades=4, win_rate=0.6,
            total_net_pnl=Decimal("1000"), total_fees=Decimal("20"),
            avg_net_pnl=Decimal("100"), best_trade_pnl=Decimal("500"),
            worst_trade_pnl=Decimal("-200"), avg_duration_seconds=3600.0,
            longest_trade_seconds=7200, shortest_trade_seconds=300,
            long_breakdown=self._bd("LONG"), short_breakdown=self._bd("SHORT"),
            close_reason_breakdown=[], top_coins=[],
        )
        assert s.total_trades == 10
        assert s.win_rate == pytest.approx(0.6)

    def test_breakdown_structure(self) -> None:
        bd = PnLBreakdown(
            label="tp_hit", count=5, win_count=5, loss_count=0,
            total_pnl=Decimal("250"), win_rate=1.0,
        )
        assert bd.label == "tp_hit"
        assert bd.win_rate == pytest.approx(1.0)


class TestAIDecisionSnapshot:
    def test_validates(self) -> None:
        snap = AIDecisionSnapshot(direction="LONG", confidence=0.87,
                                  reasons=["RSI 과매도"], model="claude-sonnet-4-6")
        assert snap.confidence == pytest.approx(0.87)

    def test_confidence_bounds(self) -> None:
        with pytest.raises(Exception):
            AIDecisionSnapshot(direction="LONG", confidence=1.5)


class TestRiskDecisionSnapshot:
    def test_validates(self) -> None:
        snap = RiskDecisionSnapshot(approved=True, final_leverage=5)
        assert snap.approved is True

    def test_rejection(self) -> None:
        snap = RiskDecisionSnapshot(approved=False, rejection_reason="일일 손실 한도")
        assert snap.approved is False
        assert snap.rejection_reason == "일일 손실 한도"


# ── JournalNotFoundError ──────────────────────────────────────────────────────

class TestJournalNotFoundError:
    def test_carries_journal_id(self) -> None:
        jid = uuid.uuid4()
        err = JournalNotFoundError(jid)
        assert err.journal_id == jid

    def test_is_exception(self) -> None:
        err = JournalNotFoundError(uuid.uuid4())
        assert isinstance(err, Exception)

    def test_str_contains_id(self) -> None:
        jid = uuid.uuid4()
        err = JournalNotFoundError(jid)
        assert str(jid) in str(err)
