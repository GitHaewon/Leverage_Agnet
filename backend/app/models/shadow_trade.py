"""Shadow Trade ORM 모델."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import TIMESTAMP, Float, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PrimaryKeyMixin, TimestampMixin


class ShadowTrade(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shadow_trades"

    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    coin: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)        # LONG | SHORT
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    tp_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    sl_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    # 청산 시 업데이트
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    pnl_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_shadow_trades_user_status", "user_id", "status"),
    )
