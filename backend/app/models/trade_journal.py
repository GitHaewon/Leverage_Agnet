from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON,
    Numeric, SmallInteger, String, Text, TIMESTAMP, UniqueConstraint, UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin, TimestampMixin
from app.models.enums import (
    CLOSE_REASON_TYPE, SIGNAL_DIRECTION_TYPE,
    CloseReasonType, SignalDirectionType,
)

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.position import Position
    from app.models.signal import Signal
    from app.models.trade_log import TradeLog


class TradeJournal(Base, PrimaryKeyMixin, TimestampMixin):
    """
    거래 일지 — 포지션 종료 시 자동 생성되는 사람이 읽기 좋은 기록.

    trade_logs는 금융 회계용 원장이고,
    trade_journals는 AI 판단 근거 + 사용자 주석이 포함된 분석 레코드다.
    """
    __tablename__ = "trade_journals"

    # ── 관계 FK ──────────────────────────────────────────────────────────────────
    trade_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trade_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("signals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── 시간 스냅샷 ───────────────────────────────────────────────────────────────
    entry_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    # ── 거래 식별 ─────────────────────────────────────────────────────────────────
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    coin: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[SignalDirectionType] = mapped_column(SIGNAL_DIRECTION_TYPE, nullable=False)
    leverage: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_ai_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # ── 저널 핵심 필드 ────────────────────────────────────────────────────────────
    strategy: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ai_decision: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    risk_decision: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    entry_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── PnL 스냅샷 ────────────────────────────────────────────────────────────────
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    pnl_percentage: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    close_reason: Mapped[CloseReasonType] = mapped_column(CLOSE_REASON_TYPE, nullable=False)

    # ── 사용자 주석 ───────────────────────────────────────────────────────────────
    user_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 제약조건 & 인덱스 ─────────────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint("trade_log_id", name="trade_journals_trade_log_unique"),
        UniqueConstraint("position_id", name="trade_journals_position_unique"),
        CheckConstraint("exit_time >= entry_time", name="trade_journals_time_order"),
        CheckConstraint("duration_seconds >= 0", name="trade_journals_duration_positive"),
        CheckConstraint("leverage >= 1 AND leverage <= 20", name="trade_journals_leverage_range"),
        Index("idx_trade_journals_user_created", "user_id", "created_at"),
        Index("idx_trade_journals_user_coin", "user_id", "coin", "created_at"),
        Index("idx_trade_journals_user_direction", "user_id", "direction", "created_at"),
        Index("idx_trade_journals_user_pnl", "user_id", "net_pnl"),
        Index("idx_trade_journals_entry_time", "user_id", "entry_time"),
        Index("idx_trade_journals_close_reason", "user_id", "close_reason"),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="trade_journals")
    position: Mapped["Position"] = relationship(back_populates="trade_journal")
    signal: Mapped["Signal | None"] = relationship(back_populates="trade_journals")
    trade_log: Mapped["TradeLog"] = relationship(back_populates="trade_journal")

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60

    def __repr__(self) -> str:
        return (
            f"<TradeJournal id={self.id} {self.symbol} {self.direction} "
            f"net_pnl={self.net_pnl} reason={self.close_reason}>"
        )
