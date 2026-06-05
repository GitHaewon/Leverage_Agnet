"""008_create_orders

Revision ID: 008
Revises: 007
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("position_id", sa.UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exchange_account_id", sa.UUID(as_uuid=True), sa.ForeignKey("exchange_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exchange_order_id", sa.String(100), nullable=True),
        sa.Column("client_order_id", sa.String(100), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("order_type", sa.Enum(name="order_type_enum", create_type=False), nullable=False),
        sa.Column("side", sa.Enum(name="order_side_type", create_type=False), nullable=False),
        sa.Column("purpose", sa.Enum(name="order_purpose_type", create_type=False), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("trigger_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("filled_quantity", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Numeric(20, 8), nullable=True),
        # GENERATED ALWAYS AS 컬럼
        sa.Column(
            "remaining_quantity",
            sa.Numeric(20, 8),
            sa.Computed("quantity - filled_quantity", persisted=True),
            nullable=False,
        ),
        sa.Column("status", sa.Enum(name="order_status_type", create_type=False), nullable=False, server_default="pending"),
        sa.Column("reject_reason", sa.Text, nullable=True),
        sa.Column("retry_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("max_retries", sa.SmallInteger, nullable=False, server_default="3"),
        sa.Column("last_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("fee", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("fee_asset", sa.String(10), nullable=True),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("quantity > 0", name="orders_quantity_positive"),
        sa.CheckConstraint("filled_quantity >= 0 AND filled_quantity <= quantity", name="orders_filled_not_exceed"),
        sa.CheckConstraint("retry_count >= 0 AND retry_count <= max_retries", name="orders_retry_not_exceed"),
        sa.CheckConstraint("order_type != 'limit' OR price IS NOT NULL", name="orders_limit_price_required"),
        sa.CheckConstraint(
            "order_type NOT IN ('stop_market', 'take_profit_market') OR trigger_price IS NOT NULL",
            name="orders_trigger_price_required",
        ),
        sa.CheckConstraint("fee >= 0", name="orders_fee_non_negative"),
    )
    op.create_index("idx_orders_position", "orders", ["position_id", "created_at"])
    op.create_index("idx_orders_user_created", "orders", ["user_id", "created_at"])
    op.create_index("idx_orders_exchange_order_id", "orders", ["exchange_order_id"],
                    postgresql_where=sa.text("exchange_order_id IS NOT NULL"))
    op.create_index("idx_orders_open_status", "orders", ["exchange_account_id", "created_at"],
                    postgresql_where=sa.text("status IN ('pending', 'open', 'partially_filled')"))
    op.create_index("idx_orders_retry", "orders", ["last_retry_at", "retry_count"],
                    postgresql_where=sa.text("status = 'rejected' AND retry_count < max_retries"))


def downgrade() -> None:
    for idx in ["idx_orders_retry", "idx_orders_open_status", "idx_orders_exchange_order_id",
                "idx_orders_user_created", "idx_orders_position"]:
        op.drop_index(idx, table_name="orders")
    op.drop_table("orders")
