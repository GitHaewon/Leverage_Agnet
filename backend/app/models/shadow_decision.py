"""Shadow Decision ORM 모델 — 파이프라인 사이클당 결정 스냅샷."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    UUID, Boolean, ForeignKey, Index, Integer,
    Numeric, String, TIMESTAMP, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PrimaryKeyMixin


class ShadowDecision(PrimaryKeyMixin, Base):
    __tablename__ = "shadow_decisions"

    # ── 파이프라인 실행 식별 ─────────────────────────────────────────────────────
    run_id:     Mapped[str] = mapped_column(String(36), nullable=False)
    user_id:    Mapped[str] = mapped_column(String(36), nullable=False)
    coin:       Mapped[str] = mapped_column(String(10), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    # ── DecisionEngine 출력 ──────────────────────────────────────────────────────
    market_regime:  Mapped[str | None]     = mapped_column(String(20),    nullable=True)
    chart_score:    Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    strategy_type:  Mapped[str | None]     = mapped_column(String(30),    nullable=True)
    long_score:     Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    short_score:    Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    risk_score:     Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    min_long_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    min_short_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    max_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    decision_score_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── TradeCandidate ───────────────────────────────────────────────────────────
    candidate_action:   Mapped[str | None]     = mapped_column(String(5),     nullable=True)
    expected_entry:     Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_loss:          Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    take_profit:        Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    candidate_rr:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4),  nullable=True)
    candidate_leverage: Mapped[int | None]     = mapped_column(Integer,        nullable=True)

    # ── ReviewerAgent 결과 ───────────────────────────────────────────────────────
    ai_decision:               Mapped[str | None]  = mapped_column(String(10),    nullable=True)
    ai_confidence:             Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    ai_critical_contradiction: Mapped[bool | None] = mapped_column(Boolean,       nullable=True)

    # ── RiskEngine 결과 ──────────────────────────────────────────────────────────
    risk_passed:        Mapped[bool | None] = mapped_column(Boolean,     nullable=True)
    risk_reject_reason: Mapped[str | None]  = mapped_column(String(100), nullable=True)

    # ── 최종 결과 ────────────────────────────────────────────────────────────────
    final_action:    Mapped[str]      = mapped_column(String(5),   nullable=False)
    rejection_stage: Mapped[str | None] = mapped_column(String(30),  nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── 체결된 경우 shadow_trades 연결 ───────────────────────────────────────────
    shadow_trade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shadow_trades.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_sdec_user_coin_decided", "user_id", "coin", "decided_at"),
        Index("ix_sdec_final_action",      "final_action", "decided_at"),
    )
