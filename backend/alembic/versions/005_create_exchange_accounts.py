"""005_create_exchange_accounts

Revision ID: 005
Revises: 004
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, INET

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_accounts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exchange", sa.Enum(name="exchange_type", create_type=False), nullable=False, server_default="binance"),
        sa.Column("label", sa.String(100), nullable=False, server_default="Main Account"),
        sa.Column("encrypted_api_key", sa.Text, nullable=False),
        sa.Column("encrypted_api_secret", sa.Text, nullable=False),
        sa.Column("encryption_iv", sa.Text, nullable=False),
        sa.Column("key_fingerprint", sa.String(16), nullable=True),
        sa.Column("is_testnet", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("permissions", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("health_status", sa.Enum(name="health_status_type", create_type=False), nullable=False, server_default="healthy"),
        sa.Column("consecutive_failures", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("last_health_check_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text, nullable=True),
        sa.Column("cached_balance_usdt", sa.Numeric(20, 8), nullable=True),
        sa.Column("balance_updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("NOT ('Withdraw' = ANY(permissions))", name="exchange_accounts_no_withdraw"),
        sa.CheckConstraint("consecutive_failures >= 0", name="exchange_accounts_failures_range"),
        sa.CheckConstraint("cached_balance_usdt IS NULL OR cached_balance_usdt >= 0", name="exchange_accounts_balance_non_negative"),
    )
    op.create_index("idx_exchange_accounts_user_active", "exchange_accounts", ["user_id", "is_active"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_exchange_accounts_health_check", "exchange_accounts", ["last_health_check_at"],
                    postgresql_where=sa.text("is_active = TRUE AND deleted_at IS NULL"))
    op.create_index("idx_exchange_accounts_unhealthy", "exchange_accounts", ["user_id", "health_status"],
                    postgresql_where=sa.text("health_status != 'healthy' AND deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_index("idx_exchange_accounts_unhealthy", table_name="exchange_accounts")
    op.drop_index("idx_exchange_accounts_health_check", table_name="exchange_accounts")
    op.drop_index("idx_exchange_accounts_user_active", table_name="exchange_accounts")
    op.drop_table("exchange_accounts")
