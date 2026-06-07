"""
Trade Journal Pydantic v2 스키마.

모든 API 입출력은 이 스키마를 통과한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import CloseReasonType, SignalDirectionType


# ── 내부 중첩 스키마 ──────────────────────────────────────────────────────────

class AIDecisionSnapshot(BaseModel):
    """synthesis 에이전트가 내린 AI 판단 스냅샷."""
    model_config = ConfigDict(extra="allow")

    direction: Literal["LONG", "SHORT", "HOLD"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    model: str = "claude-sonnet-4-6"
    tokens_used: int | None = None


class RiskDecisionSnapshot(BaseModel):
    """risk_manager 에이전트 판단 스냅샷."""
    model_config = ConfigDict(extra="allow")

    approved: bool
    final_leverage: int | None = None
    quantity: Decimal | None = None
    rejection_reason: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)


# ── 생성 / 수정 스키마 ────────────────────────────────────────────────────────

class TradeJournalCreate(BaseModel):
    """서비스 레이어에서 저널 생성 시 사용 (API 직접 노출 아님)."""
    trade_log_id: uuid.UUID
    position_id: uuid.UUID
    user_id: uuid.UUID
    signal_id: uuid.UUID | None = None
    entry_time: datetime
    exit_time: datetime
    symbol: str = Field(max_length=20)
    coin: str = Field(max_length=10)
    direction: SignalDirectionType
    leverage: int = Field(ge=1, le=20)
    is_ai_trade: bool = True
    strategy: str | None = Field(default=None, max_length=200)
    ai_decision: dict[str, Any] | None = None
    risk_decision: dict[str, Any] | None = None
    entry_reason: str | None = None
    exit_reason: str | None = None
    net_pnl: Decimal
    pnl_percentage: Decimal
    duration_seconds: int = Field(ge=0)
    close_reason: CloseReasonType
    user_notes: str | None = None


class TradeJournalUpdate(BaseModel):
    """사용자가 직접 수정 가능한 필드만 허용 (user_notes)."""
    model_config = ConfigDict(str_strip_whitespace=True)

    user_notes: str | None = Field(default=None, max_length=2000)


# ── 응답 스키마 ───────────────────────────────────────────────────────────────

class TradeJournalResponse(BaseModel):
    """단건 조회 및 목록 응답."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_log_id: uuid.UUID
    position_id: uuid.UUID
    user_id: uuid.UUID
    signal_id: uuid.UUID | None

    entry_time: datetime
    exit_time: datetime
    symbol: str
    coin: str
    direction: SignalDirectionType
    leverage: int
    is_ai_trade: bool

    strategy: str | None
    ai_decision: dict[str, Any] | None
    risk_decision: dict[str, Any] | None
    entry_reason: str | None
    exit_reason: str | None

    net_pnl: Decimal
    pnl_percentage: Decimal
    duration_seconds: int
    close_reason: CloseReasonType
    user_notes: str | None

    created_at: datetime
    updated_at: datetime


class TradeJournalListResponse(BaseModel):
    """목록 응답 (페이지네이션)."""
    items: list[TradeJournalResponse]
    total: int
    page: int
    size: int
    pages: int


# ── 검색 파라미터 스키마 ──────────────────────────────────────────────────────

class JournalSearchParams(BaseModel):
    """GET /journals/search 쿼리 파라미터."""
    model_config = ConfigDict(str_strip_whitespace=True)

    coin: str | None = Field(default=None, max_length=10)
    symbol: str | None = Field(default=None, max_length=20)
    direction: SignalDirectionType | None = None
    close_reason: CloseReasonType | None = None
    is_ai_trade: bool | None = None
    pnl_min: Decimal | None = None
    pnl_max: Decimal | None = None
    entry_from: datetime | None = None
    entry_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)

    @field_validator("pnl_max")
    @classmethod
    def pnl_max_gte_min(cls, v: Decimal | None, info: Any) -> Decimal | None:
        pnl_min = info.data.get("pnl_min")
        if v is not None and pnl_min is not None and v < pnl_min:
            raise ValueError("pnl_max must be >= pnl_min")
        return v

    @field_validator("entry_to")
    @classmethod
    def entry_to_after_from(cls, v: datetime | None, info: Any) -> datetime | None:
        entry_from = info.data.get("entry_from")
        if v is not None and entry_from is not None and v <= entry_from:
            raise ValueError("entry_to must be after entry_from")
        return v


# ── 통계 응답 스키마 ──────────────────────────────────────────────────────────

class PnLBreakdown(BaseModel):
    """방향별 / 청산유형별 PnL 분해."""
    label: str
    count: int
    win_count: int
    loss_count: int
    total_pnl: Decimal
    win_rate: float  # 0.0 ~ 1.0


class JournalStatsResponse(BaseModel):
    """GET /journals/stats 응답."""
    # 기간
    from_date: datetime | None
    to_date: datetime | None

    # 전체 집계
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate: float              # 0.0 ~ 1.0
    total_net_pnl: Decimal
    total_fees: Decimal
    avg_net_pnl: Decimal
    best_trade_pnl: Decimal | None
    worst_trade_pnl: Decimal | None

    # 시간 분석
    avg_duration_seconds: float
    longest_trade_seconds: int | None
    shortest_trade_seconds: int | None

    # 방향별
    long_breakdown: PnLBreakdown
    short_breakdown: PnLBreakdown

    # 청산 유형별
    close_reason_breakdown: list[PnLBreakdown]

    # 코인별 (상위 5)
    top_coins: list[PnLBreakdown]
