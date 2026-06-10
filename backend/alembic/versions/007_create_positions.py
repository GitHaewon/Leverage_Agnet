"""007_create_positions

Revision ID: 007
Revises: 006
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exchange_account_id", sa.UUID(as_uuid=True), sa.ForeignKey("exchange_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signal_id", sa.UUID(as_uuid=True), sa.ForeignKey("signals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("exchange_position_id", sa.String(100), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("coin", sa.String(10), nullable=False),
        sa.Column("direction", PgENUM(name="signal_direction_type", create_type=False), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("leverage", sa.SmallInteger, nullable=False),
        sa.Column("margin_used", sa.Numeric(20, 8), nullable=True),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=False),    # NOT NULL — 절대 규칙
        sa.Column("liquidation_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("trailing_stop_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("trailing_stop_callback", sa.Numeric(5, 2), nullable=True),
        sa.Column("status", PgENUM(name="position_status_type", create_type=False), nullable=False, server_default="open"),
        sa.Column("close_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("fee_paid", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("close_reason", PgENUM(name="close_reason_type", create_type=False), nullable=True),
        sa.Column("is_ai_trade", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("stop_loss IS NOT NULL", name="positions_stop_loss_required"),
        sa.CheckConstraint("leverage >= 1 AND leverage <= 20", name="positions_leverage_range"),
        sa.CheckConstraint("quantity > 0", name="positions_quantity_positive"),
        sa.CheckConstraint("entry_price > 0", name="positions_entry_price_positive"),
        sa.CheckConstraint("direction IN ('LONG', 'SHORT')", name="positions_direction_valid"),
        sa.CheckConstraint(
            "(status = 'open') OR (status IN ('closed', 'liquidated') AND close_price IS NOT NULL)",
            name="positions_closed_has_close_price",
        ),
        sa.CheckConstraint("closed_at IS NULL OR closed_at >= opened_at", name="positions_closed_at_after_opened"),
    )
    op.create_index("idx_positions_user_open", "positions", ["user_id", "opened_at"],
                    postgresql_where=sa.text("status = 'open'"))
    op.create_index("idx_positions_account_open_count", "positions", ["exchange_account_id"],
                    postgresql_where=sa.text("status = 'open'"))
    op.create_index("idx_positions_user_coin_open", "positions", ["user_id", "coin"],
                    postgresql_where=sa.text("status = 'open'"))
    op.create_index("idx_positions_signal", "positions", ["signal_id"],
                    postgresql_where=sa.text("signal_id IS NOT NULL"))
    op.create_index("idx_positions_open_liquidation", "positions", ["liquidation_price"],
                    postgresql_where=sa.text("status = 'open' AND liquidation_price IS NOT NULL"))
    op.create_index("idx_positions_user_closed", "positions", ["user_id", "closed_at"],
                    postgresql_where=sa.text("status IN ('closed', 'liquidated')"))


def downgrade() -> None:
    for idx in ["idx_positions_user_closed", "idx_positions_open_liquidation",
                "idx_positions_signal", "idx_positions_user_coin_open",
                "idx_positions_account_open_count", "idx_positions_user_open"]:
        op.drop_index(idx, table_name="positions")
    op.drop_table("positions")
