"""
Trade Journal Service — 비즈니스 로직.

아키텍처 규칙: 로직은 Service에만 위치한다.
Repository는 SQL/ORM 쿼리만 담당한다.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade_journal import TradeJournal
from app.repositories.trade_journal_repository import TradeJournalRepository
from app.schemas.trade_journal import (
    JournalSearchParams,
    JournalStatsResponse,
    TradeJournalCreate,
    TradeJournalListResponse,
    TradeJournalResponse,
    TradeJournalUpdate,
)


class TradeJournalService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = TradeJournalRepository(db)

    # ── 자동 생성 (포지션 종료 시 호출) ──────────────────────────────────────────

    async def create_from_closed_position(
        self,
        *,
        # position 정보
        position_id: uuid.UUID,
        user_id: uuid.UUID,
        trade_log_id: uuid.UUID,
        signal_id: uuid.UUID | None,
        symbol: str,
        coin: str,
        direction: str,
        leverage: int,
        is_ai_trade: bool,
        entry_price: Decimal,
        close_price: Decimal,
        opened_at: datetime,
        closed_at: datetime,
        duration_seconds: int,
        close_reason: str,
        net_pnl: Decimal,
        pnl_percentage: Decimal,
        # signal + agent 정보 (없으면 None)
        signal_reasons: list[str] | None = None,
        ai_decision_data: dict[str, Any] | None = None,
        risk_decision_data: dict[str, Any] | None = None,
    ) -> TradeJournal:
        """
        포지션 종료 직후 호출 — Journal 레코드를 자동 생성한다.
        이미 동일 position_id의 저널이 있으면 기존 레코드를 반환한다 (멱등).
        """
        existing = await self._repo.get_by_position_id(position_id)
        if existing is not None:
            return existing

        strategy = _extract_strategy(ai_decision_data)
        entry_reason = _build_entry_reason(signal_reasons)
        exit_reason = _build_exit_reason(close_reason)

        data = TradeJournalCreate(
            trade_log_id=trade_log_id,
            position_id=position_id,
            user_id=user_id,
            signal_id=signal_id,
            entry_time=opened_at,
            exit_time=closed_at,
            symbol=symbol,
            coin=coin,
            direction=direction,
            leverage=leverage,
            is_ai_trade=is_ai_trade,
            strategy=strategy,
            ai_decision=ai_decision_data,
            risk_decision=risk_decision_data,
            entry_reason=entry_reason,
            exit_reason=exit_reason,
            net_pnl=net_pnl,
            pnl_percentage=pnl_percentage,
            duration_seconds=duration_seconds,
            close_reason=close_reason,
            user_notes=None,
        )
        return await self._repo.create(data)

    # ── 조회 ─────────────────────────────────────────────────────────────────────

    async def get_journal(
        self, journal_id: uuid.UUID, user_id: uuid.UUID
    ) -> TradeJournalResponse:
        journal = await self._repo.get_by_id(journal_id, user_id)
        if journal is None:
            raise JournalNotFoundError(journal_id)
        return TradeJournalResponse.model_validate(journal)

    async def list_journals(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
    ) -> TradeJournalListResponse:
        journals, total = await self._repo.list_by_user(user_id, page, size)
        return TradeJournalListResponse(
            items=[TradeJournalResponse.model_validate(j) for j in journals],
            total=total,
            page=page,
            size=size,
            pages=math.ceil(total / size) if total > 0 else 1,
        )

    # ── 검색 ─────────────────────────────────────────────────────────────────────

    async def search_journals(
        self, user_id: uuid.UUID, params: JournalSearchParams
    ) -> TradeJournalListResponse:
        journals, total = await self._repo.search(user_id, params)
        return TradeJournalListResponse(
            items=[TradeJournalResponse.model_validate(j) for j in journals],
            total=total,
            page=params.page,
            size=params.size,
            pages=math.ceil(total / params.size) if total > 0 else 1,
        )

    # ── 수정 ─────────────────────────────────────────────────────────────────────

    async def update_notes(
        self,
        journal_id: uuid.UUID,
        user_id: uuid.UUID,
        body: TradeJournalUpdate,
    ) -> TradeJournalResponse:
        journal = await self._repo.update_notes(journal_id, user_id, body.user_notes)
        if journal is None:
            raise JournalNotFoundError(journal_id)
        return TradeJournalResponse.model_validate(journal)

    # ── 통계 ─────────────────────────────────────────────────────────────────────

    async def get_stats(
        self,
        user_id: uuid.UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> JournalStatsResponse:
        return await self._repo.get_stats(user_id, from_date, to_date)


# ── 예외 ─────────────────────────────────────────────────────────────────────

class JournalNotFoundError(Exception):
    def __init__(self, journal_id: uuid.UUID) -> None:
        super().__init__(f"Journal {journal_id} not found")
        self.journal_id = journal_id


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _extract_strategy(ai_decision: dict[str, Any] | None) -> str | None:
    """
    AI 판단 데이터에서 전략 이름을 추출한다.
    synthesis 에이전트의 signals_fired 목록을 조합해 전략 레이블을 생성한다.
    """
    if not ai_decision:
        return None
    signals = ai_decision.get("signals_fired") or ai_decision.get("signals") or []
    if signals:
        return " + ".join(str(s).upper() for s in signals[:3])
    reasons = ai_decision.get("reasons") or []
    if reasons:
        first = str(reasons[0])
        return first[:100] if len(first) > 100 else first
    return None


def _build_entry_reason(signal_reasons: list[str] | None) -> str | None:
    """signal.reasons 배열을 줄바꿈 구분 텍스트로 조합한다."""
    if not signal_reasons:
        return None
    return "\n".join(f"• {r}" for r in signal_reasons)


_CLOSE_REASON_LABELS: dict[str, str] = {
    "tp_hit":       "익절 (Take Profit 도달)",
    "sl_hit":       "손절 (Stop Loss 도달)",
    "manual":       "수동 종료",
    "liquidated":   "강제 청산",
    "emergency":    "긴급 청산",
    "dca_reversal": "DCA 반전 청산",
}


def _build_exit_reason(close_reason: str) -> str:
    return _CLOSE_REASON_LABELS.get(close_reason, close_reason)
