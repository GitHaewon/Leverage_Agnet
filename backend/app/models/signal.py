from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint, Index, Numeric, SmallInteger,
    String, Text, TIMESTAMP,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin
from app.models.enums import (
    SIGNAL_DIRECTION_TYPE, SIGNAL_STATUS_TYPE,
    SignalDirectionType, SignalStatusType,
)

if TYPE_CHECKING:
    from app.models.position import Position
    from app.models.trade_log import TradeLog
    from app.models.agent_decision import AgentDecision


class Signal(Base, PrimaryKeyMixin):
    """AI 시그널 — 에이전트 파이프라인의 최종 출력."""
    __tablename__ = "signals"

    # ── 시그널 대상 ──────────────────────────────────────────────────────────────
    coin: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)

    # ── 핵심 데이터 ──────────────────────────────────────────────────────────────
    direction: Mapped[SignalDirectionType] = mapped_column(
        SIGNAL_DIRECTION_TYPE, nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False           # 0.0000 ~ 1.0000
    )

    # ── 가격 정보 (금융 정밀도 DECIMAL(20,8)) ───────────────────────────────────
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    leverage: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rr_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)

    # ── 근거 ─────────────────────────────────────────────────────────────────────
    reasons: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default="{}"
    )

    # ── 에이전트 점수 ────────────────────────────────────────────────────────────
    technical_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    market_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    # ── 상태 ─────────────────────────────────────────────────────────────────────
    status: Mapped[SignalStatusType] = mapped_column(
        SIGNAL_STATUS_TYPE, nullable=False, server_default="active"
    )
    executed_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    # ── 유효기간 ─────────────────────────────────────────────────────────────────
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    # created_at만 (updated_at 없음 — 시그널은 불변)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="NOW()"
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="signals_confidence_range",
        ),
        CheckConstraint(
            "rr_ratio IS NULL OR rr_ratio >= 2.0",
            name="signals_rr_ratio_minimum",
        ),
        CheckConstraint(
            "leverage IS NULL OR (leverage >= 1 AND leverage <= 20)",
            name="signals_leverage_range",
        ),
        CheckConstraint(
            "entry_price > 0",
            name="signals_price_positive",
        ),
        CheckConstraint(
            "direction = 'HOLD' OR (take_profit IS NOT NULL AND stop_loss IS NOT NULL)",
            name="signals_tp_sl_required_for_direction",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="signals_expires_after_created",
        ),
        CheckConstraint(
            "(technical_score IS NULL OR (technical_score >= -1 AND technical_score <= 1)) AND "
            "(sentiment_score IS NULL OR (sentiment_score >= -1 AND sentiment_score <= 1)) AND "
            "(market_score IS NULL OR (market_score >= -1 AND market_score <= 1))",
            name="signals_score_range",
        ),
        # 코인별 활성 시그널 1개 (동일 코인 중복 방지)
        Index(
            "idx_signals_coin_active_unique",
            "coin",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        Index(
            "idx_signals_active_created",
            "status", "created_at",
            postgresql_where="status = 'active'",
        ),
        Index(
            "idx_signals_expires_at",
            "expires_at",
            postgresql_where="status = 'active'",
        ),
        Index(
            "idx_signals_confidence",
            "confidence", "created_at",
            postgresql_where="status = 'active'",
        ),
        Index(
            "idx_signals_direction_coin",
            "direction", "coin", "created_at",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    positions: Mapped[list["Position"]] = relationship(back_populates="signal")
    trade_logs: Mapped[list["TradeLog"]] = relationship(back_populates="signal")
    agent_decisions: Mapped[list["AgentDecision"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Signal id={self.id} {self.coin} {self.direction} "
            f"conf={self.confidence} status={self.status}>"
        )
