from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, TIMESTAMP, UUID
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(Base, PrimaryKeyMixin):
    """append-only 감사 로그 — UPDATE/DELETE는 DB 트리거로 차단."""
    __tablename__ = "audit_logs"

    # 삭제된 계정은 NULL 유지 (ON DELETE SET NULL)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="NOW()"
    )

    __table_args__ = (
        Index(
            "idx_audit_logs_user_action",
            "user_id", "action", "created_at",
            postgresql_where="user_id IS NOT NULL",
        ),
        Index("idx_audit_logs_action_created", "action", "created_at"),
    )

    user: Mapped["User | None"] = relationship(back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action} user_id={self.user_id}>"
