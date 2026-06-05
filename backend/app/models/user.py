from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, Index, SmallInteger,
    String, Text, TIMESTAMP, UUID,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    PLAN_TYPE, RISK_PROFILE_TYPE,
    PlanType, RiskProfileType,
)

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.user_settings import UserSettings
    from app.models.exchange_account import ExchangeAccount
    from app.models.position import Position
    from app.models.order import Order
    from app.models.trade_log import TradeLog
    from app.models.notification import Notification
    from app.models.refresh_token import RefreshToken
    from app.models.audit_log import AuditLog


class User(Base, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    # ── 인증 정보 ────────────────────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── 프로파일 ─────────────────────────────────────────────────────────────────
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan: Mapped[PlanType] = mapped_column(
        PLAN_TYPE, nullable=False, server_default="free"
    )
    risk_profile: Mapped[RiskProfileType] = mapped_column(
        RISK_PROFILE_TYPE, nullable=False, server_default="moderate"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="Asia/Seoul"
    )

    # ── 이메일 인증 ──────────────────────────────────────────────────────────────
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    email_verify_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verify_expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 2FA ──────────────────────────────────────────────────────────────────────
    is_2fa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_backup_codes: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text()), nullable=True
    )

    # ── 보안 ─────────────────────────────────────────────────────────────────────
    login_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            r"email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'",
            name="users_email_format",
        ),
        CheckConstraint(
            "login_attempts >= 0 AND login_attempts <= 10",
            name="users_login_attempts_range",
        ),
        # 로그인 조회 — active 사용자만 unique (삭제 계정 이메일 재사용 허용)
        Index(
            "idx_users_email_active",
            "email",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "idx_users_deleted_at",
            "deleted_at",
            postgresql_where="deleted_at IS NOT NULL",
        ),
        Index(
            "idx_users_plan",
            "plan",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    subscription: Mapped["Subscription | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    settings: Mapped["UserSettings | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    exchange_accounts: Mapped[list["ExchangeAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    positions: Mapped[list["Position"]] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    trade_logs: Mapped[list["TradeLog"]] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} plan={self.plan}>"
