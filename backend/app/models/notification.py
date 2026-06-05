from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, SmallInteger,
    String, Text, TIMESTAMP, UUID,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin
from app.models.enums import (
    NOTIFICATION_CHANNEL, NOTIFICATION_TYPE_ENUM,
    NotificationChannelType, NotificationTypeEnum,
)

if TYPE_CHECKING:
    from app.models.user import User


class Notification(Base, PrimaryKeyMixin):
    __tablename__ = "notifications"

    # ── 관계 FK ──────────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── 알림 내용 ────────────────────────────────────────────────────────────────
    type: Mapped[NotificationTypeEnum] = mapped_column(
        NOTIFICATION_TYPE_ENUM, nullable=False
    )
    channel: Mapped[NotificationChannelType] = mapped_column(
        NOTIFICATION_CHANNEL, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # 느슨한 결합 — 관련 엔티티 UUID를 JSON에 저장 (FK 없음)
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # ── 발송 상태 ────────────────────────────────────────────────────────────────
    is_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 읽음 처리 (Web Push 전용) ────────────────────────────────────────────────
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # ── 타임스탬프 ───────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="NOW()"
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="notifications_retry_non_negative"),
        CheckConstraint(
            "sent_at IS NULL OR sent_at >= created_at",
            name="notifications_sent_at_after_created",
        ),
        Index(
            "idx_notifications_pending",
            "created_at",
            postgresql_where=(
                "is_sent = FALSE AND (next_retry_at IS NULL OR next_retry_at <= NOW())"
            ),
        ),
        Index(
            "idx_notifications_retry",
            "next_retry_at",
            postgresql_where="is_sent = FALSE AND retry_count > 0 AND retry_count < 3",
        ),
        Index(
            "idx_notifications_user_created",
            "user_id", "created_at",
            postgresql_where="channel = 'web_push'",
        ),
        Index(
            "idx_notifications_unread",
            "user_id",
            postgresql_where="channel = 'web_push' AND read_at IS NULL AND is_sent = TRUE",
        ),
        Index("idx_notifications_user_type", "user_id", "type", "created_at"),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="notifications")

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} user_id={self.user_id} "
            f"type={self.type} channel={self.channel} sent={self.is_sent}>"
        )
