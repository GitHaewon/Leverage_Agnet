"""create reflection_reports table

Revision ID: 019
Revises: 018
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reflection_reports",

        # PK
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),

        # 관계 FK
        sa.Column(
            "position_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "journal_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("trade_journals.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # 핵심 4-field output
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("strengths", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("mistakes", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("improvements", sa.JSON, nullable=False, server_default="[]"),

        # 심층 분석
        sa.Column("entry_analysis", sa.Text, nullable=True),
        sa.Column("pnl_cause", sa.Text, nullable=True),
        sa.Column("risk_rule_violations", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("ai_grade", sa.String(1), nullable=False, server_default="C"),

        # 거래 컨텍스트 스냅샷
        sa.Column("trade_context", sa.JSON, nullable=True),

        # 모델 메타
        sa.Column("model_used", sa.String(50), nullable=False),
        sa.Column("tokens_input", sa.Integer, nullable=True),
        sa.Column("tokens_output", sa.Integer, nullable=True),

        # 타임스탬프
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # 제약조건
    op.create_unique_constraint(
        "reflection_reports_position_unique",
        "reflection_reports",
        ["position_id"],
    )
    op.create_check_constraint(
        "reflection_reports_grade_valid",
        "reflection_reports",
        "ai_grade IN ('A', 'B', 'C', 'D')",
    )

    # 인덱스
    op.create_index(
        "idx_reflection_reports_user_created",
        "reflection_reports",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_reflection_reports_user_grade",
        "reflection_reports",
        ["user_id", "ai_grade"],
    )

    # updated_at 자동 갱신 트리거
    op.execute("""
        CREATE TRIGGER trg_reflection_reports_updated_at
        BEFORE UPDATE ON reflection_reports
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_reflection_reports_updated_at ON reflection_reports;")
    op.drop_index("idx_reflection_reports_user_grade", table_name="reflection_reports")
    op.drop_index("idx_reflection_reports_user_created", table_name="reflection_reports")
    op.drop_table("reflection_reports")
