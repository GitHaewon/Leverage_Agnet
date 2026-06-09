"""
AI Trading Coach 주간 리포트 ORM 모델.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Index, Integer, String, Text, UUID
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PrimaryKeyMixin, TimestampMixin


class CoachingReport(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "coaching_reports"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    # 전체 통계
    overall_stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # 세부 통계 (JSON 배열)
    hourly_stats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weekday_stats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    coin_stats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    strategy_stats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    repeated_mistakes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    emotional_patterns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    risk_behavior_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Claude 코칭 출력
    coach_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strengths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blind_spots: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weekly_goal: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    # 메타
    skip_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model_used: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_coaching_report_user_period", "user_id", "period_end"),
    )
