"""create shadow_trades table

Shadow Trading 가상 거래 기록 테이블.

실제 주문 없이 Risk 검증을 통과한 시그널을 가상으로 실행하여
Entry/Exit/TP/SL/PnL/Duration을 추적한다.

Revision ID: 021
Revises: 020
Create Date: 2026-06-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_trades",
        # ── PrimaryKeyMixin ─────────────────────────────────────────────────
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # ── 포지션 식별 ──────────────────────────────────────────────────────
        sa.Column("user_id",   sa.String(36),  nullable=False),
        sa.Column("coin",      sa.String(10),  nullable=False),   # BTC | ETH
        sa.Column("symbol",    sa.String(20),  nullable=False),   # BTCUSDT | ETHUSDT
        sa.Column("direction", sa.String(5),   nullable=False),   # LONG | SHORT
        # ── 진입 조건 (Risk 검증 통과 값) ────────────────────────────────────
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("tp_price",    sa.Numeric(20, 8), nullable=False),
        sa.Column("sl_price",    sa.Numeric(20, 8), nullable=False),
        sa.Column("quantity",    sa.Numeric(20, 8), nullable=False),
        sa.Column("leverage",    sa.Integer(),       nullable=False),
        # ── 상태 ─────────────────────────────────────────────────────────────
        sa.Column(
            "status",
            sa.String(12),
            nullable=False,
            server_default="OPEN",      # OPEN | TP_HIT | SL_HIT | CANCELLED
        ),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # ── 청산 결과 (shadow_monitor_worker 업데이트) ────────────────────────
        sa.Column("exit_price",        sa.Numeric(20, 8),          nullable=True),
        sa.Column("pnl_usdt",          sa.Float(),                  nullable=True),
        sa.Column("duration_seconds",  sa.Float(),                  nullable=True),
        sa.Column("closed_at",         sa.TIMESTAMP(timezone=True), nullable=True),
        # ── TimestampMixin ──────────────────────────────────────────────────
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 사용자별 OPEN 거래 조회 인덱스 (shadow_monitor_worker 30초 주기 쿼리 최적화)
    op.create_index(
        "ix_shadow_trades_user_status",
        "shadow_trades",
        ["user_id", "status"],
    )

    # status 단독 인덱스 — 전체 OPEN 거래 조회 (user_id 없이 전체 순회)
    op.create_index(
        "ix_shadow_trades_status",
        "shadow_trades",
        ["status"],
    )

    # updated_at 자동 갱신 트리거
    op.execute("""
        CREATE OR REPLACE FUNCTION update_shadow_trades_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_shadow_trades_updated_at
        BEFORE UPDATE ON shadow_trades
        FOR EACH ROW EXECUTE FUNCTION update_shadow_trades_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_shadow_trades_updated_at ON shadow_trades")
    op.execute("DROP FUNCTION IF EXISTS update_shadow_trades_updated_at()")
    op.drop_index("ix_shadow_trades_status",      table_name="shadow_trades")
    op.drop_index("ix_shadow_trades_user_status", table_name="shadow_trades")
    op.drop_table("shadow_trades")
