"""010_create_agent_decisions

Revision ID: 010
Revises: 009
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("signal_id", sa.UUID(as_uuid=True), sa.ForeignKey("signals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name", sa.String(50), nullable=False),
        sa.Column("agent_version", sa.String(20), nullable=False, server_default="1.0"),
        sa.Column("input_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("output_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("score", sa.Numeric(5, 4), nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column("is_approved", sa.Boolean, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column("tokens_input", sa.Integer, nullable=True),
        sa.Column("tokens_output", sa.Integer, nullable=True),
        sa.Column("api_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "agent_name IN ('technical_analyst', 'sentiment', 'market_structure', 'synthesis', 'risk_manager')",
            name="agent_decisions_agent_name_valid",
        ),
        sa.CheckConstraint("score IS NULL OR (score >= -1 AND score <= 1)", name="agent_decisions_score_range"),
        sa.CheckConstraint("latency_ms >= 0", name="agent_decisions_latency_positive"),
        sa.CheckConstraint(
            "(tokens_input IS NULL OR tokens_input >= 0) AND (tokens_output IS NULL OR tokens_output >= 0)",
            name="agent_decisions_tokens_positive",
        ),
    )
    op.create_index("idx_agent_decisions_signal", "agent_decisions", ["signal_id", "agent_name"])
    op.create_index("idx_agent_decisions_agent_latency", "agent_decisions", ["agent_name", "latency_ms", "created_at"])
    op.create_index("idx_agent_decisions_synthesis_cost", "agent_decisions", ["created_at", "api_cost_usd"],
                    postgresql_where=sa.text("agent_name = 'synthesis'"))
    op.create_index("idx_agent_decisions_rejected", "agent_decisions", ["created_at"],
                    postgresql_where=sa.text("agent_name = 'risk_manager' AND is_approved = FALSE"))


def downgrade() -> None:
    for idx in ["idx_agent_decisions_rejected", "idx_agent_decisions_synthesis_cost",
                "idx_agent_decisions_agent_latency", "idx_agent_decisions_signal"]:
        op.drop_index(idx, table_name="agent_decisions")
    op.drop_table("agent_decisions")
