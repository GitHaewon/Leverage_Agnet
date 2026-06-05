from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint, Computed, ForeignKey, Index, Numeric, SmallInteger,
    String, Text, TIMESTAMP, UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin, TimestampMixin
from app.models.enums import (
    ORDER_PURPOSE_TYPE, ORDER_SIDE_TYPE, ORDER_STATUS_TYPE, ORDER_TYPE_ENUM,
    OrderPurposeType, OrderSideType, OrderStatusType, OrderTypeEnum,
)

if TYPE_CHECKING:
    from app.models.position import Position
    from app.models.user import User
    from app.models.exchange_account import ExchangeAccount


class Order(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "orders"

    # ── 관계 FK ──────────────────────────────────────────────────────────────────
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
    )
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

    # ── 거래소 주문 ID ───────────────────────────────────────────────────────────
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    client_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── 주문 기본 정보 ───────────────────────────────────────────────────────────
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    order_type: Mapped[OrderTypeEnum] = mapped_column(ORDER_TYPE_ENUM, nullable=False)
    side: Mapped[OrderSideType] = mapped_column(ORDER_SIDE_TYPE, nullable=False)
    purpose: Mapped[OrderPurposeType] = mapped_column(ORDER_PURPOSE_TYPE, nullable=False)

    # ── 수량 및 가격 ─────────────────────────────────────────────────────────────
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    # ── 체결 정보 ────────────────────────────────────────────────────────────────
    filled_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default="0"
    )
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    # GENERATED ALWAYS AS — PostgreSQL 계산 컬럼
    remaining_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        Computed("quantity - filled_quantity", persisted=True),
        nullable=False,
    )

    # ── 상태 ─────────────────────────────────────────────────────────────────────
    status: Mapped[OrderStatusType] = mapped_column(
        ORDER_STATUS_TYPE, nullable=False, server_default="pending"
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 재시도 ───────────────────────────────────────────────────────────────────
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    max_retries: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    last_retry_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 수수료 ───────────────────────────────────────────────────────────────────
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, server_default="0")
    fee_asset: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── 타임스탬프 ───────────────────────────────────────────────────────────────
    executed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint("quantity > 0", name="orders_quantity_positive"),
        CheckConstraint(
            "filled_quantity >= 0 AND filled_quantity <= quantity",
            name="orders_filled_not_exceed",
        ),
        CheckConstraint(
            "retry_count >= 0 AND retry_count <= max_retries",
            name="orders_retry_not_exceed",
        ),
        CheckConstraint(
            "order_type != 'limit' OR price IS NOT NULL",
            name="orders_limit_price_required",
        ),
        CheckConstraint(
            "order_type NOT IN ('stop_market', 'take_profit_market') OR trigger_price IS NOT NULL",
            name="orders_trigger_price_required",
        ),
        CheckConstraint("fee >= 0", name="orders_fee_non_negative"),
        Index("idx_orders_position", "position_id", "created_at"),
        Index("idx_orders_user_created", "user_id", "created_at"),
        Index(
            "idx_orders_exchange_order_id",
            "exchange_order_id",
            postgresql_where="exchange_order_id IS NOT NULL",
        ),
        Index(
            "idx_orders_open_status",
            "exchange_account_id", "created_at",
            postgresql_where="status IN ('pending', 'open', 'partially_filled')",
        ),
        Index(
            "idx_orders_retry",
            "last_retry_at", "retry_count",
            postgresql_nulls_first=True,
            postgresql_where="status = 'rejected' AND retry_count < max_retries",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    position: Mapped["Position"] = relationship(back_populates="orders")
    user: Mapped["User"] = relationship(back_populates="orders")
    exchange_account: Mapped["ExchangeAccount"] = relationship(back_populates="orders")

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} {self.symbol} {self.side} "
            f"{self.order_type} status={self.status}>"
        )
