"""expand shadow trade performance metrics

Revision ID: 024
Revises: 023
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    nullable = [
        ("signal_id", sa.String(36)),
        ("position_size_usdt", sa.Numeric(20, 8)),
        ("margin_usdt", sa.Numeric(20, 8)),
        ("tp_distance", sa.Numeric(20, 8)),
        ("sl_distance", sa.Numeric(20, 8)),
        ("expected_max_loss_usdt", sa.Numeric(20, 8)),
        ("leverage_reason", sa.String(600)),
        ("reviewer_input_summary", sa.JSON()),
        ("reviewer_result", sa.String(12)),
        ("reviewer_score", sa.Float()),
        ("market_regime", sa.String(32)),
        ("exit_reason", sa.String(32)),
        ("gross_pnl_usdt", sa.Numeric(20, 8)),
        ("net_pnl_usdt", sa.Numeric(20, 8)),
    ]
    for name, type_ in nullable:
        op.add_column("shadow_trades", sa.Column(name, type_, nullable=True))
    op.add_column(
        "shadow_trades",
        sa.Column(
            "strategy_version",
            sa.String(64),
            nullable=False,
            server_default="legacy_unknown",
        ),
    )

    for name in (
        "entry_fee_usdt", "exit_fee_usdt", "funding_fee_usdt",
        "estimated_slippage_usdt", "mfe_usdt", "mae_usdt",
    ):
        op.add_column(
            "shadow_trades",
            sa.Column(name, sa.Numeric(20, 8), nullable=False, server_default="0"),
        )
    op.add_column(
        "shadow_trades",
        sa.Column(
            "pnl_calculation_status",
            sa.String(24),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    for name in ("data_error", "system_error"):
        op.add_column(
            "shadow_trades",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    # Legacy pnl_usdt was gross PnL. Its unknown costs must not be presented as net.
    op.execute(
        """
        UPDATE shadow_trades
        SET gross_pnl_usdt = pnl_usdt,
            net_pnl_usdt = NULL,
            pnl_calculation_status = 'GROSS_FALLBACK',
            exit_reason = status
        WHERE pnl_usdt IS NOT NULL
        """
    )


def downgrade() -> None:
    for name in (
        "system_error", "data_error", "pnl_calculation_status", "mae_usdt", "mfe_usdt",
        "estimated_slippage_usdt", "funding_fee_usdt", "exit_fee_usdt",
        "entry_fee_usdt", "net_pnl_usdt", "gross_pnl_usdt", "exit_reason",
        "market_regime", "reviewer_score", "reviewer_result",
        "reviewer_input_summary", "leverage_reason", "expected_max_loss_usdt",
        "sl_distance", "tp_distance", "margin_usdt", "position_size_usdt",
        "signal_id", "strategy_version",
    ):
        op.drop_column("shadow_trades", name)
