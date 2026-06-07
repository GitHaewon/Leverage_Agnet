"""
Trade Journal API — /api/v1/journals

엔드포인트:
  GET    /journals              목록 (페이지네이션)
  GET    /journals/stats        통계
  GET    /journals/search       검색
  GET    /journals/{id}         단건 조회
  PATCH  /journals/{id}         사용자 메모 수정
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.trade_journal import (
    JournalSearchParams,
    JournalStatsResponse,
    TradeJournalListResponse,
    TradeJournalResponse,
    TradeJournalUpdate,
)
from app.services.trade_journal_service import JournalNotFoundError, TradeJournalService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/journals", tags=["journals"])


def _get_service(db: AsyncSession = Depends(get_db)) -> TradeJournalService:
    return TradeJournalService(db)


# ── 목록 ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=TradeJournalListResponse)
async def list_journals(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: TradeJournalService = Depends(_get_service),
) -> TradeJournalListResponse:
    return await service.list_journals(current_user.id, page=page, size=size)


# ── 통계 (경로 충돌 방지 — {id} 앞에 위치) ───────────────────────────────────

@router.get("/stats", response_model=JournalStatsResponse)
async def get_stats(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    service: TradeJournalService = Depends(_get_service),
) -> JournalStatsResponse:
    return await service.get_stats(current_user.id, from_date=from_date, to_date=to_date)


# ── 검색 ─────────────────────────────────────────────────────────────────────

@router.get("/search", response_model=TradeJournalListResponse)
async def search_journals(
    coin: str | None = Query(default=None, max_length=10),
    symbol: str | None = Query(default=None, max_length=20),
    direction: str | None = Query(default=None),
    close_reason: str | None = Query(default=None),
    is_ai_trade: bool | None = Query(default=None),
    pnl_min: float | None = Query(default=None),
    pnl_max: float | None = Query(default=None),
    entry_from: datetime | None = Query(default=None),
    entry_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: TradeJournalService = Depends(_get_service),
) -> TradeJournalListResponse:
    from decimal import Decimal
    from app.models.enums import CloseReasonType, SignalDirectionType

    params = JournalSearchParams(
        coin=coin,
        symbol=symbol,
        direction=SignalDirectionType(direction) if direction else None,
        close_reason=CloseReasonType(close_reason) if close_reason else None,
        is_ai_trade=is_ai_trade,
        pnl_min=Decimal(str(pnl_min)) if pnl_min is not None else None,
        pnl_max=Decimal(str(pnl_max)) if pnl_max is not None else None,
        entry_from=entry_from,
        entry_to=entry_to,
        page=page,
        size=size,
    )
    return await service.search_journals(current_user.id, params)


# ── 단건 조회 ─────────────────────────────────────────────────────────────────

@router.get("/{journal_id}", response_model=TradeJournalResponse)
async def get_journal(
    journal_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: TradeJournalService = Depends(_get_service),
) -> TradeJournalResponse:
    try:
        return await service.get_journal(journal_id, current_user.id)
    except JournalNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")


# ── 메모 수정 ─────────────────────────────────────────────────────────────────

@router.patch("/{journal_id}", response_model=TradeJournalResponse)
async def update_journal_notes(
    journal_id: uuid.UUID,
    body: TradeJournalUpdate,
    current_user: User = Depends(get_current_user),
    service: TradeJournalService = Depends(_get_service),
) -> TradeJournalResponse:
    try:
        return await service.update_notes(journal_id, current_user.id, body)
    except JournalNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")
