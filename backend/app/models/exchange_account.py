from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, Numeric, SmallInteger,
    String, Text, TIMESTAMP, UUID,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    EXCHANGE_TYPE, HEALTH_STATUS_TYPE,
    ExchangeType, HealthStatusType,
)

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.position import Position
    from app.models.order import Order


class ExchangeAccount(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "exchange_accounts"

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── 거래소 정보 ──────────────────────────────────────────────────────────────
    exchange: Mapped[ExchangeType] = mapped_column(
        EXCHANGE_TYPE, nullable=False, server_default="binance"
    )
    label: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="Main Account"
    )

    # ── API Key (AES-256-GCM 암호화 저장) ───────────────────────────────────────
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_iv: Mapped[str] = mapped_column(Text, nullable=False)
    key_fingerprint: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # ── 환경 및 설정 ─────────────────────────────────────────────────────────────
    is_testnet: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default="{}"
    )

    # ── 헬스체크 ─────────────────────────────────────────────────────────────────
    health_status: Mapped[HealthStatusType] = mapped_column(
        HEALTH_STATUS_TYPE, nullable=False, server_default="healthy"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 잔고 캐시 ────────────────────────────────────────────────────────────────
    cached_balance_usdt: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    balance_updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "NOT ('Withdraw' = ANY(permissions))",
            name="exchange_accounts_no_withdraw",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="exchange_accounts_failures_range",
        ),
        CheckConstraint(
            "cached_balance_usdt IS NULL OR cached_balance_usdt >= 0",
            name="exchange_accounts_balance_non_negative",
        ),
        Index(
            "idx_exchange_accounts_user_active",
            "user_id", "is_active",
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "idx_exchange_accounts_health_check",
            "last_health_check_at",
            postgresql_where="is_active = TRUE AND deleted_at IS NULL",
        ),
        Index(
            "idx_exchange_accounts_unhealthy",
            "user_id", "health_status",
            postgresql_where="health_status != 'healthy' AND deleted_at IS NULL",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="exchange_accounts")
    positions: Mapped[list["Position"]] = relationship(back_populates="exchange_account")
    orders: Mapped[list["Order"]] = relationship(back_populates="exchange_account")

    def __repr__(self) -> str:
        return (
            f"<ExchangeAccount id={self.id} user_id={self.user_id} "
            f"exchange={self.exchange} testnet={self.is_testnet}>"
        )
