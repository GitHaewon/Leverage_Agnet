"""001_create_enums

Revision ID: 001
Revises:
Create Date: 2026-06-05
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    op.execute("CREATE TYPE plan_type AS ENUM ('free', 'pro', 'elite')")
    op.execute("CREATE TYPE risk_profile_type AS ENUM ('conservative', 'moderate', 'aggressive')")
    op.execute("CREATE TYPE billing_period_type AS ENUM ('monthly', 'yearly')")
    op.execute(
        "CREATE TYPE subscription_status_type AS ENUM "
        "('trialing', 'active', 'past_due', 'cancelled', 'incomplete', 'incomplete_expired')"
    )
    op.execute("CREATE TYPE exchange_type AS ENUM ('binance', 'bybit', 'okx')")
    op.execute("CREATE TYPE health_status_type AS ENUM ('healthy', 'degraded', 'disconnected')")
    op.execute("CREATE TYPE signal_direction_type AS ENUM ('LONG', 'SHORT', 'HOLD')")
    op.execute("CREATE TYPE signal_status_type AS ENUM ('active', 'expired', 'executed', 'dismissed')")
    op.execute(
        "CREATE TYPE position_status_type AS ENUM "
        "('open', 'closed', 'liquidated', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE close_reason_type AS ENUM "
        "('tp_hit', 'sl_hit', 'manual', 'liquidated', 'emergency', 'dca_reversal')"
    )
    op.execute(
        "CREATE TYPE order_type_enum AS ENUM "
        "('market', 'limit', 'stop_market', 'take_profit_market', 'trailing_stop')"
    )
    op.execute("CREATE TYPE order_side_type AS ENUM ('BUY', 'SELL')")
    op.execute(
        "CREATE TYPE order_purpose_type AS ENUM "
        "('entry', 'take_profit', 'stop_loss', 'emergency_close', 'dca', 'partial_close')"
    )
    op.execute(
        "CREATE TYPE order_status_type AS ENUM "
        "('pending', 'open', 'partially_filled', 'filled', 'cancelled', 'rejected', 'expired')"
    )
    op.execute("CREATE TYPE trading_mode_type AS ENUM ('full_auto', 'semi_auto', 'signal_only')")
    op.execute(
        "CREATE TYPE notification_type_enum AS ENUM "
        "('signal_new', 'order_filled', 'order_failed', 'position_closed', "
        "'liquidation_warning', 'daily_summary', 'system_alert', 'payment_failed', 'api_key_issue')"
    )
    op.execute(
        "CREATE TYPE notification_channel_type AS ENUM ('telegram', 'email', 'web_push')"
    )


def downgrade() -> None:
    for enum_name in [
        "notification_channel_type", "notification_type_enum", "trading_mode_type",
        "order_status_type", "order_purpose_type", "order_side_type", "order_type_enum",
        "close_reason_type", "position_status_type", "signal_status_type",
        "signal_direction_type", "health_status_type", "exchange_type",
        "subscription_status_type", "billing_period_type", "risk_profile_type", "plan_type",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
