"""
MemoryStore 단위 테스트.

Qdrant 클라이언트와 FastEmbed를 Mock 처리한다.
검증 대상:
  - JournalDocument 텍스트 + 페이로드 생성
  - ReflectionDocument 텍스트 + 페이로드 생성
  - StrategyDocument 텍스트 + 페이로드 생성
  - MemoryStore.upsert_journal() — Qdrant에 올바른 데이터 전달
  - MemoryStore.upsert_reflection()
  - MemoryStore.delete_by_position()
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.documents import JournalDocument, ReflectionDocument, StrategyDocument
from app.memory.store import MemoryStore


# ── ORM 픽스처 ────────────────────────────────────────────────────────────────

def make_journal(
    *,
    net_pnl: str = "131.50",
    close_reason: str = "tp_hit",
    direction: str = "LONG",
    is_win: bool = True,
    strategy: str | None = "RSI_OVERSOLD + EMA200",
    entry_reason: str | None = "RSI 42.3 과매도 진입",
    exit_reason: str | None = "목표가 도달",
    signal_reasons: list[str] | None = None,
) -> MagicMock:
    j = MagicMock()
    j.id = uuid.uuid4()
    j.position_id = uuid.uuid4()
    j.user_id = uuid.uuid4()
    j.signal_id = uuid.uuid4()
    j.coin = "BTC"
    j.symbol = "BTCUSDT"
    j.direction = direction
    j.leverage = 5
    j.is_ai_trade = True
    j.strategy = strategy
    j.entry_reason = entry_reason
    j.exit_reason = exit_reason
    j.net_pnl = Decimal(net_pnl)
    j.pnl_percentage = Decimal("13.15") if is_win else Decimal("-4.85")
    j.duration_seconds = 10800
    j.close_reason = close_reason
    j.entry_time = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
    j.exit_time = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    j.ai_decision = {
        "direction": direction,
        "confidence": 0.87,
        "reasons": signal_reasons or ["RSI(14)=42.3 과매도", "Funding Rate 역발상"],
        "technical_score": 0.72,
        "sentiment_score": -0.31,
        "market_score": 0.58,
    }
    j.risk_decision = {"approved": True, "final_leverage": 5, "risk_reward": 2.71}
    return j


def make_reflection(
    *,
    ai_grade: str = "B",
    net_pnl: float = 131.50,
    has_violations: bool = False,
) -> MagicMock:
    r = MagicMock()
    r.id = uuid.uuid4()
    r.position_id = uuid.uuid4()
    r.user_id = uuid.uuid4()
    r.journal_id = uuid.uuid4()
    r.summary = "BTC LONG 포지션 목표가 달성 — RSI 과매도 진입 우수"
    r.strengths = ["RSI 과매도 진입 정확", "Funding Rate 역발상 성공"]
    r.mistakes = ["TP 설정 소폭 보수적"]
    r.improvements = ["부분 익절 전략 도입 검토"]
    r.entry_analysis = "RSI 42.3에서 EMA200 지지 반등 진입 — 기술적으로 우수"
    r.pnl_cause = "기술적 과매도 반등 + 숏 스퀴즈 복합 효과"
    r.risk_rule_violations = ["R:R 위반"] if has_violations else []
    r.ai_grade = ai_grade
    r.trade_context = {
        "coin": "BTC",
        "direction": "LONG",
        "leverage": 5,
        "net_pnl": str(net_pnl),
        "close_reason": "tp_hit",
    }
    r.created_at = datetime(2026, 6, 9, 12, 5, tzinfo=timezone.utc)
    return r


# ── JournalDocument 테스트 ────────────────────────────────────────────────────

class TestJournalDocument:

    def test_builds_embed_text_with_core_fields(self) -> None:
        j = make_journal()
        doc = JournalDocument.from_orm(j)
        assert "BTC" in doc.embed_text
        assert "LONG" in doc.embed_text
        assert "tp_hit" in doc.embed_text
        assert "5x" in doc.embed_text

    def test_includes_strategy_in_text(self) -> None:
        j = make_journal(strategy="RSI_OVERSOLD + EMA200")
        doc = JournalDocument.from_orm(j)
        assert "RSI_OVERSOLD" in doc.embed_text

    def test_includes_entry_reason_in_text(self) -> None:
        j = make_journal(entry_reason="RSI 42.3 과매도 진입")
        doc = JournalDocument.from_orm(j)
        assert "RSI 42.3" in doc.embed_text

    def test_includes_signal_reasons_in_text(self) -> None:
        j = make_journal(signal_reasons=["Funding Rate -0.02%", "EMA200 지지"])
        doc = JournalDocument.from_orm(j)
        assert "Funding Rate" in doc.embed_text

    def test_payload_has_required_filter_fields(self) -> None:
        j = make_journal()
        doc = JournalDocument.from_orm(j)
        for key in ["user_id", "coin", "direction", "is_win", "close_reason", "net_pnl"]:
            assert key in doc.payload

    def test_payload_is_win_true_for_positive_pnl(self) -> None:
        j = make_journal(net_pnl="131.50")
        doc = JournalDocument.from_orm(j)
        assert doc.payload["is_win"] is True

    def test_payload_is_win_false_for_negative_pnl(self) -> None:
        j = make_journal(net_pnl="-48.50")
        doc = JournalDocument.from_orm(j)
        assert doc.payload["is_win"] is False

    def test_point_id_equals_position_id(self) -> None:
        j = make_journal()
        doc = JournalDocument.from_orm(j)
        assert doc.point_id == str(j.position_id)

    def test_payload_source_is_journal(self) -> None:
        j = make_journal()
        doc = JournalDocument.from_orm(j)
        assert doc.payload["source"] == "journal"

    def test_short_direction_in_text(self) -> None:
        j = make_journal(direction="SHORT", close_reason="sl_hit")
        doc = JournalDocument.from_orm(j)
        assert "SHORT" in doc.embed_text
        assert "sl_hit" in doc.embed_text

    def test_duration_converted_to_hours_minutes(self) -> None:
        j = make_journal()
        j.duration_seconds = 10800  # 3시간
        doc = JournalDocument.from_orm(j)
        assert "3시간" in doc.embed_text


# ── ReflectionDocument 테스트 ─────────────────────────────────────────────────

class TestReflectionDocument:

    def test_builds_embed_text_with_summary(self) -> None:
        r = make_reflection()
        doc = ReflectionDocument.from_orm(r)
        assert "BTC LONG" in doc.embed_text
        assert "목표가 달성" in doc.embed_text

    def test_includes_grade_in_text(self) -> None:
        r = make_reflection(ai_grade="A")
        doc = ReflectionDocument.from_orm(r)
        assert "[A등급]" in doc.embed_text

    def test_includes_strengths(self) -> None:
        r = make_reflection()
        doc = ReflectionDocument.from_orm(r)
        assert "RSI 과매도 진입 정확" in doc.embed_text

    def test_includes_mistakes(self) -> None:
        r = make_reflection()
        doc = ReflectionDocument.from_orm(r)
        assert "TP 설정 소폭 보수적" in doc.embed_text

    def test_includes_improvements(self) -> None:
        r = make_reflection()
        doc = ReflectionDocument.from_orm(r)
        assert "부분 익절" in doc.embed_text

    def test_violations_included_in_text(self) -> None:
        r = make_reflection(has_violations=True)
        doc = ReflectionDocument.from_orm(r)
        assert "리스크 위반" in doc.embed_text

    def test_payload_has_required_fields(self) -> None:
        r = make_reflection()
        doc = ReflectionDocument.from_orm(r)
        for key in ["user_id", "position_id", "ai_grade", "is_win", "has_violations"]:
            assert key in doc.payload

    def test_payload_source_is_reflection(self) -> None:
        r = make_reflection()
        doc = ReflectionDocument.from_orm(r)
        assert doc.payload["source"] == "reflection"


# ── StrategyDocument 테스트 ───────────────────────────────────────────────────

class TestStrategyDocument:

    def test_builds_embed_text_with_signal_context(self) -> None:
        j = make_journal()
        doc = StrategyDocument.from_journal(j)
        assert "BTC" in doc.embed_text
        assert "신뢰도" in doc.embed_text

    def test_includes_scores_in_text(self) -> None:
        j = make_journal()
        doc = StrategyDocument.from_journal(j)
        assert "기술" in doc.embed_text
        assert "감성" in doc.embed_text
        assert "시장" in doc.embed_text

    def test_includes_signal_reasons(self) -> None:
        j = make_journal(signal_reasons=["RSI(14)=42.3 과매도"])
        doc = StrategyDocument.from_journal(j)
        assert "RSI(14)=42.3" in doc.embed_text

    def test_payload_source_is_strategy(self) -> None:
        j = make_journal()
        doc = StrategyDocument.from_journal(j)
        assert doc.payload["source"] == "strategy"

    def test_payload_has_confidence(self) -> None:
        j = make_journal()
        doc = StrategyDocument.from_journal(j)
        assert "confidence" in doc.payload
        assert doc.payload["confidence"] == pytest.approx(0.87)


# ── MemoryStore 테스트 ────────────────────────────────────────────────────────

class TestMemoryStore:

    def _make_store(self) -> tuple[MemoryStore, AsyncMock]:
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=True)
        mock_client.upsert = AsyncMock()
        store = MemoryStore(client=mock_client)
        store._initialized = True  # 초기화 스킵
        return store, mock_client

    @patch("app.memory.store.embed_text", return_value=[0.1] * 384)
    async def test_upsert_journal_calls_qdrant_twice(
        self, mock_embed: MagicMock
    ) -> None:
        store, mock_client = self._make_store()
        journal = make_journal()

        await store.upsert_journal(journal)

        # journals + strategy 컬렉션에 각각 1회 upsert
        assert mock_client.upsert.call_count == 2

    @patch("app.memory.store.embed_text", return_value=[0.1] * 384)
    async def test_upsert_journal_uses_position_id_as_point_id(
        self, mock_embed: MagicMock
    ) -> None:
        store, mock_client = self._make_store()
        journal = make_journal()

        await store.upsert_journal(journal)

        call_args = mock_client.upsert.call_args_list[0]
        points = call_args.kwargs["points"]
        assert points[0].id == str(journal.position_id)

    @patch("app.memory.store.embed_text", return_value=[0.2] * 384)
    async def test_upsert_reflection_calls_qdrant_once(
        self, mock_embed: MagicMock
    ) -> None:
        store, mock_client = self._make_store()
        report = make_reflection()

        await store.upsert_reflection(report)

        assert mock_client.upsert.call_count == 1

    @patch("app.memory.store.embed_text", return_value=[0.3] * 384)
    async def test_upsert_uses_correct_vector_from_embed(
        self, mock_embed: MagicMock
    ) -> None:
        store, mock_client = self._make_store()
        journal = make_journal()

        await store.upsert_journal(journal)

        call_args = mock_client.upsert.call_args_list[0]
        points = call_args.kwargs["points"]
        assert points[0].vector == [0.3] * 384

    async def test_delete_by_position_calls_delete_on_all_collections(self) -> None:
        store, mock_client = self._make_store()
        mock_client.delete = AsyncMock()
        position_id = str(uuid.uuid4())

        await store.delete_by_position(position_id)

        assert mock_client.delete.call_count == 3  # 세 컬렉션 모두
