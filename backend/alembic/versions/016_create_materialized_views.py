"""016_create_materialized_views

Revision ID: 016
Revises: 015
Create Date: 2026-06-05
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 사용자 일별 수익률 집계 뷰
    op.execute("""
        CREATE MATERIALIZED VIEW user_performance_daily AS
        SELECT
            user_id,
            date_trunc('day', created_at)::DATE AS trade_date,
            COUNT(*)                             AS trade_count,
            COUNT(*) FILTER (WHERE net_pnl > 0)  AS win_count,
            COUNT(*) FILTER (WHERE net_pnl < 0)  AS loss_count,
            SUM(net_pnl)                         AS daily_pnl,
            SUM(fee_paid)                        AS total_fees,
            AVG(duration_seconds)                AS avg_duration_seconds
        FROM trade_logs
        GROUP BY user_id, date_trunc('day', created_at)::DATE
        WITH NO DATA;
    """)

    op.execute("""
        CREATE UNIQUE INDEX ON user_performance_daily (user_id, trade_date);
    """)

    # 초기 데이터 채우기
    op.execute("REFRESH MATERIALIZED VIEW user_performance_daily;")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS user_performance_daily")
