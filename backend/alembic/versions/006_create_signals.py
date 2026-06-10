"""006_create_signals

Revision ID: 006
Revises: 005
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM
from sqlalchemy.dialects.postgresql import ARRAY

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("coin", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("direction", PgENUM(name="signal_direction_type", create_type=False), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=True),
        sa.Column("leverage", sa.SmallInteger, nullable=True),
        sa.Column("rr_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("reasons", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("technical_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("sentiment_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("market_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("status", PgENUM(name="signal_status_type", create_type=False), nullable=False, server_default="active"),
        sa.Column("executed_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="signals_confidence_range"),
        sa.CheckConstraint("rr_ratio IS NULL OR rr_ratio >= 2.0", name="signals_rr_ratio_minimum"),
        sa.CheckConstraint("leverage IS NULL OR (leverage >= 1 AND leverage <= 20)", name="signals_leverage_range"),
        sa.CheckConstraint("entry_price > 0", name="signals_price_positive"),
        sa.CheckConstraint(
            "direction = 'HOLD' OR (take_profit IS NOT NULL AND stop_loss IS NOT NULL)",
            name="signals_tp_sl_required_for_direction",
        ),
        sa.CheckConstraint("expires_at > created_at", name="signals_expires_after_created"),
        sa.CheckConstraint(
            "(technical_score IS NULL OR (technical_score >= -1 AND technical_score <= 1)) AND "
            "(sentiment_score IS NULL OR (sentiment_score >= -1 AND sentiment_score <= 1)) AND "
            "(market_score IS NULL OR (market_score >= -1 AND market_score <= 1))",
            name="signals_score_range",
        ),
    )
    # 코인별 활성 시그널 유니크 (partial unique index)
    op.create_index("idx_signals_coin_active_unique", "signals", ["coin"],
                    unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_index("idx_signals_active_created", "signals", ["status", "created_at"],
                    postgresql_where=sa.text("status = 'active'"))
    op.create_index("idx_signals_expires_at", "signals", ["expires_at"],
                    postgresql_where=sa.text("status = 'active'"))
    op.create_index("idx_signals_confidence", "signals", ["confidence", "created_at"],
                    postgresql_where=sa.text("status = 'active'"))
    op.create_index("idx_signals_direction_coin", "signals", ["direction", "coin", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_signals_direction_coin", table_name="signals")
    op.drop_index("idx_signals_confidence", table_name="signals")
    op.drop_index("idx_signals_expires_at", table_name="signals")
    op.drop_index("idx_signals_active_created", table_name="signals")
    op.drop_index("idx_signals_coin_active_unique", table_name="signals")
    op.drop_table("signals")
