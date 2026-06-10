"""014_create_ohlcv_timescale

TimescaleDB 하이퍼테이블 생성.
create_hypertable()은 Alembic op를 사용할 수 없어 raw SQL로 실행한다.

Revision ID: 014
Revises: 013
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ohlcv",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False, primary_key=True),
        sa.Column("coin", sa.String(10), nullable=False, primary_key=True),
        sa.Column("interval", sa.String(5), nullable=False, primary_key=True),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(24, 8), nullable=False),
        sa.CheckConstraint("high >= low", name="ohlcv_high_gte_low"),
        sa.CheckConstraint("volume >= 0", name="ohlcv_volume_non_negative"),
    )

    # TimescaleDB 하이퍼테이블 변환 — plain PG에서는 스킵
    op.execute("""
        DO $$
        BEGIN
            PERFORM create_hypertable('ohlcv', 'time',
                chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$;
    """)

    # 복합 unique 인덱스
    op.create_index(
        "idx_ohlcv_coin_interval_time", "ohlcv",
        ["coin", "interval", "time"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_ohlcv_coin_interval_time", table_name="ohlcv")
    op.drop_table("ohlcv")
