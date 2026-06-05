from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, String, TIMESTAMP, UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PrimaryKeyMixin, TimestampMixin
from app.models.enums import (
    BILLING_PERIOD_TYPE, PLAN_TYPE, SUBSCRIPTION_STATUS,
    BillingPeriodType, PlanType, SubscriptionStatusType,
)

if TYPE_CHECKING:
    from app.models.user import User


class Subscription(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subscriptions"

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Stripe 연동 ──────────────────────────────────────────────────────────────
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    stripe_price_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── 플랜 정보 ────────────────────────────────────────────────────────────────
    plan: Mapped[PlanType] = mapped_column(
        PLAN_TYPE, nullable=False, server_default="free"
    )
    billing_period: Mapped[BillingPeriodType | None] = mapped_column(
        BILLING_PERIOD_TYPE, nullable=True
    )
    status: Mapped[SubscriptionStatusType] = mapped_column(
        SUBSCRIPTION_STATUS, nullable=False, server_default="active"
    )

    # ── 기간 정보 ────────────────────────────────────────────────────────────────
    trial_end_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 결제 실패 관리 ───────────────────────────────────────────────────────────
    past_due_since: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    grace_period_end_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # ── 제약조건 & 인덱스 ────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "current_period_start < current_period_end",
            name="subscriptions_period_order",
        ),
        CheckConstraint(
            "(plan = 'free' AND billing_period IS NULL AND stripe_subscription_id IS NULL) "
            "OR plan != 'free'",
            name="subscriptions_free_no_billing",
        ),
        # 사용자당 활성 구독 1개만 (partial unique)
        Index(
            "idx_subscriptions_user_active",
            "user_id",
            unique=True,
            postgresql_where="status IN ('active', 'trialing', 'past_due')",
        ),
        Index(
            "idx_subscriptions_stripe_subscription",
            "stripe_subscription_id",
            postgresql_where="stripe_subscription_id IS NOT NULL",
        ),
        Index(
            "idx_subscriptions_period_end",
            "current_period_end",
            postgresql_where="status = 'active'",
        ),
        Index(
            "idx_subscriptions_grace_period",
            "grace_period_end_at",
            postgresql_where="status = 'past_due'",
        ),
    )

    # ── 관계 ─────────────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="subscription")

    def __repr__(self) -> str:
        return f"<Subscription user_id={self.user_id} plan={self.plan} status={self.status}>"
