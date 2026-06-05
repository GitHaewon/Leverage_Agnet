from __future__ import annotations

import uuid
from datetime import time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Numeric, SmallInteger,
    Text, Time, TIMESTAMP, UUID,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin
from app.models.enums import TRADING_MODE_TYPE, TradingModeType

if TYPE_CHECKING:
    from app.models.user import User


class UserSettings(Base, PrimaryKeyMixin):
    __tablename__ = "user_settings"

    # ── 관계 (1:1 with users) ────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # ── 자동매매 설정 ────────────────────────────────────────────────────────────
    mode: Mapped[TradingModeType] = mapped_column(
        TRADING_MODE_TYPE, nullable=False, server_default="signal_only"
    )
    coins: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default="{BTC,ETH}"
    )
    risk_per_trade: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0.01"
    )
    max_leverage: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="5"
    )
    daily_loss_limit: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default="100.0"
    )
    max_concurrent_positions: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1"
    )

    # ── 거래 시간 제한 ───────────────────────────────────────────────────────────
    allowed_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    allowed_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    # ── 자동매매 활성화 ──────────────────────────────────────────────────────────
    is_trading_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # ── 알림 설정 ────────────────────────────────────────────────────────────────
    notify_signal_new: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notify_order_filled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notify_position_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notify_liquidation_warn: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notify_daily_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    # updated_at만 (created_at 없음 — DDL 기준)
    updated_at: Mapped[None] = mapped_column(  # type: ignore[assignment]
        TIMESTAMP(timezone=True), nullable=False, server_default="NOW()"
    )

    # ── 제약조건 ─────────────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "risk_per_trade >= 0.005 AND risk_per_trade <= 0.05",
            name="user_settings_risk_range",
        ),
        CheckConstraint(
            "max_leverage >= 1 AND max_leverage <= 20",
            name="user_settings_leverage_range",
        ),
        CheckConstraint(
            "daily_loss_limit > 0",
            name="user_settings_daily_loss_positive",
        ),
        CheckConstraint(
            "max_concurrent_positions >= 1",
            name="user_settings_positions_positive",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="settings")

    def __repr__(self) -> str:
        return (
            f"<UserSettings user_id={self.user_id} mode={self.mode} "
            f"active={self.is_trading_active}>"
        )
