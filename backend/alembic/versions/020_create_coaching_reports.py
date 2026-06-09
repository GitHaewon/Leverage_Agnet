"""create coaching_reports table

Revision ID: 020
Revises: 019
Create Date: 2026-06-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coaching_reports",
        sa.Column("id",                  sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id",             sa.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start",        sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("period_end",          sa.TIMESTAMP(timezone=True), nullable=False),
        # 통계
        sa.Column("overall_stats",       JSON, nullable=False, server_default="{}"),
        sa.Column("hourly_stats",        JSON, nullable=False, server_default="[]"),
        sa.Column("weekday_stats",       JSON, nullable=False, server_default="[]"),
        sa.Column("coin_stats",          JSON, nullable=False, server_default="[]"),
        sa.Column("strategy_stats",      JSON, nullable=False, server_default="[]"),
        sa.Column("repeated_mistakes",   JSON, nullable=False, server_default="[]"),
        sa.Column("emotional_patterns",  JSON, nullable=False, server_default="[]"),
        sa.Column("risk_behavior_score", sa.Integer(), nullable=False, server_default="100"),
        # Claude 출력
        sa.Column("coach_summary",       sa.Text(), nullable=False, server_default=""),
        sa.Column("strengths",           JSON, nullable=False, server_default="[]"),
        sa.Column("blind_spots",         JSON, nullable=False, server_default="[]"),
        sa.Column("weekly_goal",         sa.String(500), nullable=False, server_default=""),
        # 메타
        sa.Column("skip_reason",         sa.String(200), nullable=True),
        sa.Column("model_used",          sa.String(50), nullable=False),
        sa.Column("tokens_input",        sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output",       sa.Integer(), nullable=False, server_default="0"),
        # 공통
        sa.Column("created_at",          sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",          sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_coaching_report_user_period", "coaching_reports", ["user_id", "period_end"])

    # updated_at 자동 갱신 트리거
    op.execute("""
        CREATE OR REPLACE FUNCTION update_coaching_reports_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_coaching_reports_updated_at
        BEFORE UPDATE ON coaching_reports
        FOR EACH ROW EXECUTE FUNCTION update_coaching_reports_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_coaching_reports_updated_at ON coaching_reports")
    op.execute("DROP FUNCTION IF EXISTS update_coaching_reports_updated_at()")
    op.drop_index("ix_coaching_report_user_period", table_name="coaching_reports")
    op.drop_table("coaching_reports")
