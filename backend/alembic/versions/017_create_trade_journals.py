"""create trade_journals table

Revision ID: 017
Revises: 016
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_journals",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # ── 관계 FK ──────────────────────────────────────────────────────────
        sa.Column("trade_log_id", sa.UUID(as_uuid=True), sa.ForeignKey("trade_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position_id", sa.UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signal_id", sa.UUID(as_uuid=True), sa.ForeignKey("signals.id", ondelete="SET NULL"), nullable=True),
        # ── 시간 스냅샷 ───────────────────────────────────────────────────────
        sa.Column("entry_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("exit_time", sa.TIMESTAMP(timezone=True), nullable=False),
        # ── 거래 식별 ─────────────────────────────────────────────────────────
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("coin", sa.String(10), nullable=False),
        sa.Column("direction", sa.Enum(name="signal_direction_type", create_type=False), nullable=False),
        sa.Column("leverage", sa.SmallInteger(), nullable=False),
        sa.Column("is_ai_trade", sa.Boolean(), nullable=False, server_default="true"),
        # ── 저널 핵심 필드 ────────────────────────────────────────────────────
        sa.Column("strategy", sa.String(200), nullable=True),          # "RSI_OVERSOLD + EMA200_SUPPORT"
        sa.Column("ai_decision", sa.JSON(), nullable=True),             # synthesis agent 출력 스냅샷
        sa.Column("risk_decision", sa.JSON(), nullable=True),           # risk_manager 출력 스냅샷
        sa.Column("entry_reason", sa.Text(), nullable=True),            # signal.reasons 조합 텍스트
        sa.Column("exit_reason", sa.Text(), nullable=True),             # close_reason + 부가 설명
        # ── PnL 스냅샷 (빠른 통계용 — trade_logs JOIN 불필요) ─────────────────
        sa.Column("net_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("pnl_percentage", sa.Numeric(10, 4), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("close_reason", sa.Enum(name="close_reason_type", create_type=False), nullable=False),
        # ── 사용자 주석 (후행 편집 가능) ──────────────────────────────────────
        sa.Column("user_notes", sa.Text(), nullable=True),
        # ── 타임스탬프 ────────────────────────────────────────────────────────
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        # ── 제약조건 ──────────────────────────────────────────────────────────
        sa.UniqueConstraint("trade_log_id", name="trade_journals_trade_log_unique"),
        sa.UniqueConstraint("position_id", name="trade_journals_position_unique"),
        sa.CheckConstraint("exit_time >= entry_time", name="trade_journals_time_order"),
        sa.CheckConstraint("duration_seconds >= 0", name="trade_journals_duration_positive"),
        sa.CheckConstraint("leverage >= 1 AND leverage <= 20", name="trade_journals_leverage_range"),
    )

    # ── updated_at 자동 갱신 트리거 ─────────────────────────────────────────
    op.execute("""
        CREATE TRIGGER trade_journals_updated_at
            BEFORE UPDATE ON trade_journals
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trade_journals_updated_at ON trade_journals;")
    op.drop_table("trade_journals")
