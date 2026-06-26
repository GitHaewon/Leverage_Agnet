"""add shadow decision score diagnostics

Revision ID: 023
Revises: 022
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shadow_decisions", sa.Column("long_score", sa.Numeric(6, 2), nullable=True))
    op.add_column("shadow_decisions", sa.Column("short_score", sa.Numeric(6, 2), nullable=True))
    op.add_column("shadow_decisions", sa.Column("risk_score", sa.Numeric(6, 2), nullable=True))
    op.add_column("shadow_decisions", sa.Column("min_long_score", sa.Numeric(6, 2), nullable=True))
    op.add_column("shadow_decisions", sa.Column("min_short_score", sa.Numeric(6, 2), nullable=True))
    op.add_column("shadow_decisions", sa.Column("max_risk_score", sa.Numeric(6, 2), nullable=True))
    op.add_column("shadow_decisions", sa.Column("decision_score_summary", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("shadow_decisions", "decision_score_summary")
    op.drop_column("shadow_decisions", "max_risk_score")
    op.drop_column("shadow_decisions", "min_short_score")
    op.drop_column("shadow_decisions", "min_long_score")
    op.drop_column("shadow_decisions", "risk_score")
    op.drop_column("shadow_decisions", "short_score")
    op.drop_column("shadow_decisions", "long_score")
