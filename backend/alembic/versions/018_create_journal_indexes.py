"""create trade_journals indexes

Revision ID: 018
Revises: 017
Create Date: 2026-06-08
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 사용자별 저널 목록 (최신 순) — 가장 빈번한 조회
    op.create_index(
        "idx_trade_journals_user_created",
        "trade_journals",
        ["user_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    # 코인별 필터링
    op.create_index(
        "idx_trade_journals_user_coin",
        "trade_journals",
        ["user_id", "coin", "created_at"],
    )
    # 방향별 필터링 (LONG/SHORT 승률 분석)
    op.create_index(
        "idx_trade_journals_user_direction",
        "trade_journals",
        ["user_id", "direction", "created_at"],
    )
    # PnL 범위 검색
    op.create_index(
        "idx_trade_journals_user_pnl",
        "trade_journals",
        ["user_id", "net_pnl"],
    )
    # 기간 필터 (entry_time 기준)
    op.create_index(
        "idx_trade_journals_entry_time",
        "trade_journals",
        ["user_id", "entry_time"],
    )
    # 청산 유형별 (SL/TP 비율 분석)
    op.create_index(
        "idx_trade_journals_close_reason",
        "trade_journals",
        ["user_id", "close_reason"],
    )
    # 시그널 연결 (AI 승률 추적)
    op.create_index(
        "idx_trade_journals_signal",
        "trade_journals",
        ["signal_id"],
        postgresql_where="signal_id IS NOT NULL",
    )


def downgrade() -> None:
    for idx in [
        "idx_trade_journals_user_created",
        "idx_trade_journals_user_coin",
        "idx_trade_journals_user_direction",
        "idx_trade_journals_user_pnl",
        "idx_trade_journals_entry_time",
        "idx_trade_journals_close_reason",
        "idx_trade_journals_signal",
    ]:
        op.drop_index(idx, table_name="trade_journals")
