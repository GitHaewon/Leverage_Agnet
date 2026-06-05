from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric,
    String, Text, TIMESTAMP, UUID,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.signal import Signal

# 허용 에이전트 이름 (CHECK 제약과 일치해야 함)
VALID_AGENT_NAMES = (
    "technical_analyst",
    "sentiment",
    "market_structure",
    "synthesis",
    "risk_manager",
)


class AgentDecision(Base, PrimaryKeyMixin):
    """에이전트 파이프라인의 각 결정 스냅샷 — LangGraph 디버깅 및 비용 추적."""
    __tablename__ = "agent_decisions"

    # ── 관계 FK ──────────────────────────────────────────────────────────────────
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── 에이전트 식별 ────────────────────────────────────────────────────────────
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="1.0"
    )

    # ── 입출력 (JSONB — 에이전트마다 구조 다름) ──────────────────────────────────
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    output_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # ── 핵심값 (JSONB 파싱 없이 쿼리 가능) ──────────────────────────────────────
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── 성능 추적 ────────────────────────────────────────────────────────────────
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    # ── 타임스탬프 (created_at만 — 불변) ────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="NOW()"
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "agent_name IN ('technical_analyst', 'sentiment', 'market_structure', "
            "'synthesis', 'risk_manager')",
            name="agent_decisions_agent_name_valid",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= -1 AND score <= 1)",
            name="agent_decisions_score_range",
        ),
        CheckConstraint("latency_ms >= 0", name="agent_decisions_latency_positive"),
        CheckConstraint(
            "(tokens_input IS NULL OR tokens_input >= 0) AND "
            "(tokens_output IS NULL OR tokens_output >= 0)",
            name="agent_decisions_tokens_positive",
        ),
        Index("idx_agent_decisions_signal", "signal_id", "agent_name"),
        Index("idx_agent_decisions_agent_latency", "agent_name", "latency_ms", "created_at"),
        Index(
            "idx_agent_decisions_synthesis_cost",
            "created_at", "api_cost_usd",
            postgresql_where="agent_name = 'synthesis'",
        ),
        Index(
            "idx_agent_decisions_rejected",
            "created_at",
            postgresql_where="agent_name = 'risk_manager' AND is_approved = FALSE",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    signal: Mapped["Signal"] = relationship(back_populates="agent_decisions")

    def __repr__(self) -> str:
        return (
            f"<AgentDecision id={self.id} agent={self.agent_name} "
            f"signal_id={self.signal_id} approved={self.is_approved}>"
        )
