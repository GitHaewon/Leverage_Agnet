"""009_create_trade_logs

Revision ID: 009
Revises: 008
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_logs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("position_id", sa.UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("signal_id", sa.UUID(as_uuid=True), sa.ForeignKey("signals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("coin", sa.String(10), nullable=False),
        sa.Column("direction", sa.Enum(name="signal_direction_type", create_type=False), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("close_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("leverage", sa.SmallInteger, nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("fee_paid", sa.Numeric(20, 8), nullable=False, server_default="0"),
        # GENERATED ALWAYS AS — 수수료 차감 순이익
        sa.Column(
            "net_pnl",
            sa.Numeric(20, 8),
            sa.Computed("realized_pnl - fee_paid", persisted=True),
            nullable=False,
        ),
        sa.Column("pnl_percentage", sa.Numeric(10, 4), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("close_reason", sa.Enum(name="close_reason_type", create_type=False), nullable=False),
        sa.Column("is_ai_trade", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("max_unrealized_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("max_unrealized_loss", sa.Numeric(20, 8), nullable=True),
        sa.Column("tp_hit_pct", sa.Numeric(5, 2), nullable=True),
        # 시그널 스냅샷
        sa.Column("signal_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("signal_entry_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("signal_tp", sa.Numeric(20, 8), nullable=True),
        sa.Column("signal_sl", sa.Numeric(20, 8), nullable=True),
        sa.Column("signal_rr_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("position_id", name="trade_logs_position_unique"),
        sa.CheckConstraint("direction IN ('LONG', 'SHORT')", name="trade_logs_direction_valid"),
        sa.CheckConstraint("duration_seconds >= 0", name="trade_logs_duration_positive"),
        sa.CheckConstraint("quantity > 0", name="trade_logs_quantity_positive"),
        sa.CheckConstraint("tp_hit_pct IS NULL OR (tp_hit_pct >= 0 AND tp_hit_pct <= 100)", name="trade_logs_tp_hit_range"),
    )
    op.create_index("idx_trade_logs_user_created", "trade_logs", ["user_id", "created_at"])
    op.create_index("idx_trade_logs_signal_performance", "trade_logs", ["signal_id", "net_pnl"],
                    postgresql_where=sa.text("signal_id IS NOT NULL"))
    op.create_index("idx_trade_logs_user_coin", "trade_logs", ["user_id", "coin", "created_at"])
    op.create_index("idx_trade_logs_close_reason", "trade_logs", ["user_id", "close_reason", "created_at"])


def downgrade() -> None:
    for idx in ["idx_trade_logs_close_reason", "idx_trade_logs_user_coin",
                "idx_trade_logs_signal_performance", "idx_trade_logs_user_created"]:
        op.drop_index(idx, table_name="trade_logs")
    op.drop_table("trade_logs")
