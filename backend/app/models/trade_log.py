from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, Computed, ForeignKey, Index, Integer, Numeric,
    SmallInteger, String, TIMESTAMP, UniqueConstraint, UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin
from app.models.enums import (
    CLOSE_REASON_TYPE, SIGNAL_DIRECTION_TYPE,
    CloseReasonType, SignalDirectionType,
)

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.position import Position
    from app.models.signal import Signal


class TradeLog(Base, PrimaryKeyMixin):
    """포지션 종료 시 불변 스냅샷 — 거래 분석의 Source of Truth."""
    __tablename__ = "trade_logs"

    # ── 관계 FK ──────────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("signals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── 거래 기본 정보 (포지션 종료 시 스냅샷) ──────────────────────────────────
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    coin: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[SignalDirectionType] = mapped_column(
        SIGNAL_DIRECTION_TYPE, nullable=False
    )

    # ── 진입/청산 가격 ───────────────────────────────────────────────────────────
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # ── 수익/손실 ────────────────────────────────────────────────────────────────
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    fee_paid: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default="0"
    )
    # GENERATED ALWAYS AS — 수수료 차감 순이익
    net_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        Computed("realized_pnl - fee_paid", persisted=True),
        nullable=False,
    )
    pnl_percentage: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)

    # ── 시간 ─────────────────────────────────────────────────────────────────────
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    close_reason: Mapped[CloseReasonType] = mapped_column(CLOSE_REASON_TYPE, nullable=False)

    # ── 메타 ─────────────────────────────────────────────────────────────────────
    is_ai_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # ── 회고 분석 ────────────────────────────────────────────────────────────────
    max_unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    max_unrealized_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    tp_hit_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # ── 시그널 스냅샷 (시그널 변경/삭제 후에도 당시 데이터 보존) ────────────────
    signal_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    signal_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    signal_tp: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    signal_sl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    signal_rr_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)

    # ── 타임스탬프 (created_at만 — 불변 로그) ───────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="NOW()"
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint("position_id", name="trade_logs_position_unique"),
        CheckConstraint(
            "direction IN ('LONG', 'SHORT')",
            name="trade_logs_direction_valid",
        ),
        CheckConstraint("duration_seconds >= 0", name="trade_logs_duration_positive"),
        CheckConstraint("quantity > 0", name="trade_logs_quantity_positive"),
        CheckConstraint(
            "tp_hit_pct IS NULL OR (tp_hit_pct >= 0 AND tp_hit_pct <= 100)",
            name="trade_logs_tp_hit_range",
        ),
        Index("idx_trade_logs_user_created", "user_id", "created_at"),
        Index(
            "idx_trade_logs_signal_performance",
            "signal_id", "net_pnl",
            postgresql_where="signal_id IS NOT NULL",
        ),
        Index("idx_trade_logs_user_coin", "user_id", "coin", "created_at"),
        Index("idx_trade_logs_close_reason", "user_id", "close_reason", "created_at"),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="trade_logs")
    position: Mapped["Position"] = relationship(back_populates="trade_log")
    signal: Mapped["Signal | None"] = relationship(back_populates="trade_logs")

    def __repr__(self) -> str:
        return (
            f"<TradeLog id={self.id} {self.symbol} {self.direction} "
            f"net_pnl={self.net_pnl} reason={self.close_reason}>"
        )
