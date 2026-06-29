"""Shadow Trade ORM 모델."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Boolean,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
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

    strategy_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="legacy_unknown"
    )
    experiment_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    position_size_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    margin_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    tp_distance: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    sl_distance: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    expected_max_loss_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    actual_max_loss_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    risk_budget_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    risk_budget_utilization: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    leverage_reason: Mapped[str | None] = mapped_column(String(600), nullable=True)
    reviewer_input_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewer_result: Mapped[str | None] = mapped_column(String(12), nullable=True)
    reviewer_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gross_pnl_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    entry_fee_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    exit_fee_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    entry_slippage_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    exit_slippage_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    funding_fee_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    # Compatibility field:
    # - OPEN rows: entry-only slippage estimate captured at virtual fill time.
    # - CLOSED rows: total slippage cost from calculate_shadow_pnl()
    #   (= entry_slippage_usdt + exit_slippage_usdt).
    estimated_slippage_usdt: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=0
    )
    net_pnl_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    net_return_on_margin_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    pnl_calculation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="UNKNOWN"
    )
    mfe_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    mae_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    data_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    system_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_hold_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejection_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_shadow_trades_user_status", "user_id", "status"),
        Index(
            "ix_shadow_trades_user_strategy_status",
            "user_id",
            "strategy_version",
            "status",
        ),
        UniqueConstraint(
            "signal_id",
            "strategy_version",
            name="uq_shadow_trades_signal_strategy",
        ),
    )
