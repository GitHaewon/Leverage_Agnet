from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint, ForeignKey, Index, JSON, String, Text,
    UniqueConstraint, UUID, Integer,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.position import Position
    from app.models.trade_journal import TradeJournal


class ReflectionReport(Base, PrimaryKeyMixin, TimestampMixin):
    """
    ReflectionAgent가 거래 종료 후 생성하는 AI 회고 리포트.

    trade_journals는 있는 그대로의 기록이고,
    reflection_reports는 패턴 분석 + 리스크 규칙 위반 검증 + 개선 제안이 포함된 코칭 리포트다.
    """
    __tablename__ = "reflection_reports"

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
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trade_journals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── 핵심 출력 4-field spec ─────────────────────────────────────────────────
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    mistakes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    improvements: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # ── 심층 분석 ─────────────────────────────────────────────────────────────────
    entry_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    pnl_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_rule_violations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    ai_grade: Mapped[str] = mapped_column(String(1), nullable=False, server_default="C")

    # ── 거래 컨텍스트 스냅샷 ───────────────────────────────────────────────────────
    trade_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # ── 모델 메타 ────────────────────────────────────────────────────────────────
    model_used: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── 제약조건 & 인덱스 ─────────────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint("position_id", name="reflection_reports_position_unique"),
        CheckConstraint(
            "ai_grade IN ('A', 'B', 'C', 'D')",
            name="reflection_reports_grade_valid",
        ),
        Index("idx_reflection_reports_user_created", "user_id", "created_at"),
        Index("idx_reflection_reports_user_grade", "user_id", "ai_grade"),
    )

    # ── 관계 (단방향) ──────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    position: Mapped["Position"] = relationship(foreign_keys=[position_id])
    journal: Mapped["TradeJournal | None"] = relationship(foreign_keys=[journal_id])

    def __repr__(self) -> str:
        return (
            f"<ReflectionReport id={self.id} position={self.position_id} "
            f"grade={self.ai_grade}>"
        )
