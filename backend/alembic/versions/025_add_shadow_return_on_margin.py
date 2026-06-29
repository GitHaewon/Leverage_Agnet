"""add shadow net return on margin

Revision ID: 025
Revises: 024
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shadow_trades",
        sa.Column("net_return_on_margin_pct", sa.Numeric(12, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shadow_trades", "net_return_on_margin_pct")
