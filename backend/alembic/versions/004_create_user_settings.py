"""004_create_user_settings

Revision ID: 004
Revises: 003
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("mode", sa.Enum(name="trading_mode_type", create_type=False), nullable=False, server_default="signal_only"),
        sa.Column("coins", ARRAY(sa.Text()), nullable=False, server_default="{BTC,ETH}"),
        sa.Column("risk_per_trade", sa.Numeric(5, 4), nullable=False, server_default="0.01"),
        sa.Column("max_leverage", sa.SmallInteger, nullable=False, server_default="5"),
        sa.Column("daily_loss_limit", sa.Numeric(20, 8), nullable=False, server_default="100.0"),
        sa.Column("max_concurrent_positions", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("allowed_hours_start", sa.Time, nullable=True),
        sa.Column("allowed_hours_end", sa.Time, nullable=True),
        sa.Column("is_trading_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("notify_signal_new", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notify_order_filled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notify_position_closed", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notify_liquidation_warn", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notify_daily_summary", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("quiet_hours_start", sa.Time, nullable=True),
        sa.Column("quiet_hours_end", sa.Time, nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("risk_per_trade >= 0.005 AND risk_per_trade <= 0.05", name="user_settings_risk_range"),
        sa.CheckConstraint("max_leverage >= 1 AND max_leverage <= 20", name="user_settings_leverage_range"),
        sa.CheckConstraint("daily_loss_limit > 0", name="user_settings_daily_loss_positive"),
        sa.CheckConstraint("max_concurrent_positions >= 1", name="user_settings_positions_positive"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
