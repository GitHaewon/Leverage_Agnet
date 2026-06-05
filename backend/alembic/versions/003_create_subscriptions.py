"""003_create_subscriptions

Revision ID: 003
Revises: 002
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stripe_customer_id", sa.String(100), nullable=True, unique=True),
        sa.Column("stripe_subscription_id", sa.String(100), nullable=True, unique=True),
        sa.Column("stripe_price_id", sa.String(100), nullable=True),
        sa.Column("plan", sa.Enum(name="plan_type", create_type=False), nullable=False, server_default="free"),
        sa.Column("billing_period", sa.Enum(name="billing_period_type", create_type=False), nullable=True),
        sa.Column("status", sa.Enum(name="subscription_status_type", create_type=False), nullable=False, server_default="active"),
        sa.Column("trial_end_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_period_start", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("past_due_since", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("grace_period_end_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("current_period_start < current_period_end", name="subscriptions_period_order"),
        sa.CheckConstraint(
            "(plan = 'free' AND billing_period IS NULL AND stripe_subscription_id IS NULL) OR plan != 'free'",
            name="subscriptions_free_no_billing",
        ),
    )
    op.create_index(
        "idx_subscriptions_user_active", "subscriptions", ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'trialing', 'past_due')"),
    )
    op.create_index(
        "idx_subscriptions_stripe_subscription", "subscriptions", ["stripe_subscription_id"],
        postgresql_where=sa.text("stripe_subscription_id IS NOT NULL"),
    )
    op.create_index(
        "idx_subscriptions_period_end", "subscriptions", ["current_period_end"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "idx_subscriptions_grace_period", "subscriptions", ["grace_period_end_at"],
        postgresql_where=sa.text("status = 'past_due'"),
    )


def downgrade() -> None:
    op.drop_index("idx_subscriptions_grace_period", table_name="subscriptions")
    op.drop_index("idx_subscriptions_period_end", table_name="subscriptions")
    op.drop_index("idx_subscriptions_stripe_subscription", table_name="subscriptions")
    op.drop_index("idx_subscriptions_user_active", table_name="subscriptions")
    op.drop_table("subscriptions")
