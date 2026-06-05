from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, Numeric, SmallInteger,
    String, Text, TIMESTAMP, UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin
from app.models.enums import (
    CLOSE_REASON_TYPE, POSITION_STATUS_TYPE, SIGNAL_DIRECTION_TYPE,
    CloseReasonType, PositionStatusType, SignalDirectionType,
)

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.exchange_account import ExchangeAccount
    from app.models.signal import Signal
    from app.models.order import Order
    from app.models.trade_log import TradeLog


class Position(Base, PrimaryKeyMixin):
    """포지션 — stop_loss NOT NULL 강제 (CLAUDE.md 절대 규칙)."""
    __tablename__ = "positions"

    # ── 관계 FK ──────────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exchange_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("signals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── 거래소 식별자 ────────────────────────────────────────────────────────────
    exchange_position_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── 포지션 기본 정보 ─────────────────────────────────────────────────────────
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    coin: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[SignalDirectionType] = mapped_column(
        SIGNAL_DIRECTION_TYPE, nullable=False
    )

    # ── 진입 정보 ────────────────────────────────────────────────────────────────
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    margin_used: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    # ── TP/SL (stop_loss NOT NULL — 손절 없는 포지션 절대 금지) ─────────────────
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    # ── 트레일링 스탑 ────────────────────────────────────────────────────────────
    trailing_stop_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    trailing_stop_callback: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    # ── 상태 ─────────────────────────────────────────────────────────────────────
    status: Mapped[PositionStatusType] = mapped_column(
        POSITION_STATUS_TYPE, nullable=False, server_default="open"
    )

    # ── 청산 정보 ────────────────────────────────────────────────────────────────
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fee_paid: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default="0"
    )
    close_reason: Mapped[CloseReasonType | None] = mapped_column(
        CLOSE_REASON_TYPE, nullable=True
    )

    # ── 메타 ─────────────────────────────────────────────────────────────────────
    is_ai_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 타임스탬프 ───────────────────────────────────────────────────────────────
    opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="NOW()"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "stop_loss IS NOT NULL",
            name="positions_stop_loss_required",
        ),
        CheckConstraint(
            "leverage >= 1 AND leverage <= 20",
            name="positions_leverage_range",
        ),
        CheckConstraint(
            "quantity > 0",
            name="positions_quantity_positive",
        ),
        CheckConstraint(
            "entry_price > 0",
            name="positions_entry_price_positive",
        ),
        CheckConstraint(
            "direction IN ('LONG', 'SHORT')",
            name="positions_direction_valid",
        ),
        CheckConstraint(
            "(status = 'open') OR "
            "(status IN ('closed', 'liquidated') AND close_price IS NOT NULL)",
            name="positions_closed_has_close_price",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at",
            name="positions_closed_at_after_opened",
        ),
        Index(
            "idx_positions_user_open",
            "user_id", "opened_at",
            postgresql_where="status = 'open'",
        ),
        Index(
            "idx_positions_account_open_count",
            "exchange_account_id",
            postgresql_where="status = 'open'",
        ),
        Index(
            "idx_positions_user_coin_open",
            "user_id", "coin",
            postgresql_where="status = 'open'",
        ),
        Index(
            "idx_positions_signal",
            "signal_id",
            postgresql_where="signal_id IS NOT NULL",
        ),
        Index(
            "idx_positions_open_liquidation",
            "liquidation_price",
            postgresql_where="status = 'open' AND liquidation_price IS NOT NULL",
        ),
        Index(
            "idx_positions_user_closed",
            "user_id", "closed_at",
            postgresql_where="status IN ('closed', 'liquidated')",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="positions")
    exchange_account: Mapped["ExchangeAccount"] = relationship(back_populates="positions")
    signal: Mapped["Signal | None"] = relationship(back_populates="positions")
    orders: Mapped[list["Order"]] = relationship(
        back_populates="position", cascade="all, delete-orphan"
    )
    trade_log: Mapped["TradeLog | None"] = relationship(
        back_populates="position", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Position id={self.id} {self.coin} {self.direction} "
            f"status={self.status} entry={self.entry_price}>"
        )
