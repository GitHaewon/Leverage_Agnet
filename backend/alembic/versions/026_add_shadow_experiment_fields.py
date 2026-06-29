"""add shadow experiment and risk sizing fields

Revision ID: 026
Revises: 025
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    nullable = [
        ("experiment_label", sa.String(100)),
        ("actual_max_loss_usdt", sa.Numeric(20, 8)),
        ("risk_budget_usdt", sa.Numeric(20, 8)),
        ("risk_budget_utilization", sa.Numeric(12, 8)),
        ("max_hold_seconds", sa.Integer()),
        ("rejection_code", sa.String(64)),
        ("rejection_reason", sa.String(500)),
    ]
    for name, type_ in nullable:
        op.add_column("shadow_trades", sa.Column(name, type_, nullable=True))
    for name in ("entry_slippage_usdt", "exit_slippage_usdt"):
        op.add_column(
            "shadow_trades",
            sa.Column(name, sa.Numeric(20, 8), nullable=False, server_default="0"),
        )
    op.create_index(
        "ix_shadow_trades_user_strategy_status",
        "shadow_trades",
        ["user_id", "strategy_version", "status"],
    )
    op.create_unique_constraint(
        "uq_shadow_trades_signal_strategy",
        "shadow_trades",
        ["signal_id", "strategy_version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_shadow_trades_signal_strategy",
        "shadow_trades",
        type_="unique",
    )
    op.drop_index(
        "ix_shadow_trades_user_strategy_status", table_name="shadow_trades"
    )
    for name in (
        "exit_slippage_usdt",
        "entry_slippage_usdt",
        "rejection_reason",
        "rejection_code",
        "max_hold_seconds",
        "risk_budget_utilization",
        "risk_budget_usdt",
        "actual_max_loss_usdt",
        "experiment_label",
    ):
        op.drop_column("shadow_trades", name)
