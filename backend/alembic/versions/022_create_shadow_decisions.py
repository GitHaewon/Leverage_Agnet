"""create shadow_decisions table

파이프라인이 실행될 때마다 HOLD/REJECT 포함 모든 결정을 기록한다.
체결된 경우 shadow_trades FK로 연결된다.

Revision ID: 022
Revises: 021
Create Date: 2026-06-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_decisions",
        # ── PK ──────────────────────────────────────────────────────────────────
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # ── 파이프라인 실행 식별 ─────────────────────────────────────────────────
        sa.Column("run_id",   sa.String(36),  nullable=False),
        sa.Column("user_id",  sa.String(36),  nullable=False),
        sa.Column("coin",     sa.String(10),  nullable=False),   # BTC | ETH
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # ── DecisionEngine 출력 ──────────────────────────────────────────────────
        sa.Column("market_regime",  sa.String(20),  nullable=True),  # TRENDING_UP | RANGING | …
        sa.Column("chart_score",    sa.Numeric(5, 4), nullable=True), # -1.0 ~ 1.0
        sa.Column("strategy_type",  sa.String(30),  nullable=True),  # SCALPING | INTRADAY | …
        # ── TradeCandidate (DecisionEngine이 HOLD를 낸 경우 NULL) ────────────────
        sa.Column("candidate_action",   sa.String(5),    nullable=True),  # LONG | SHORT | HOLD
        sa.Column("expected_entry",     sa.Numeric(20, 8), nullable=True),
        sa.Column("stop_loss",          sa.Numeric(20, 8), nullable=True),
        sa.Column("take_profit",        sa.Numeric(20, 8), nullable=True),
        sa.Column("candidate_rr",       sa.Numeric(8, 4),  nullable=True),
        sa.Column("candidate_leverage", sa.Integer(),      nullable=True),
        # ── ReviewerAgent 결과 ───────────────────────────────────────────────────
        sa.Column("ai_decision",               sa.String(10),  nullable=True),  # APPROVE | REJECT | ERROR | SKIPPED
        sa.Column("ai_confidence",             sa.Numeric(5, 4), nullable=True),
        sa.Column("ai_critical_contradiction", sa.Boolean(),   nullable=True),
        # ── RiskEngine 결과 ──────────────────────────────────────────────────────
        sa.Column("risk_passed",        sa.Boolean(),     nullable=True),
        sa.Column("risk_reject_reason", sa.String(100),   nullable=True),
        # ── 최종 결과 ────────────────────────────────────────────────────────────
        sa.Column("final_action",    sa.String(5),   nullable=False),  # LONG | SHORT | HOLD
        sa.Column("rejection_stage", sa.String(30),  nullable=True),   # NULL = 체결됨
        sa.Column("rejection_reason", sa.String(200), nullable=True),
        # ── 체결된 경우 shadow_trades FK ─────────────────────────────────────────
        sa.Column(
            "shadow_trade_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("shadow_trades.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # ── created_at (불변 로그) ────────────────────────────────────────────────
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_sdec_user_coin_decided",
        "shadow_decisions",
        ["user_id", "coin", sa.text("decided_at DESC")],
    )
    op.create_index(
        "ix_sdec_final_action",
        "shadow_decisions",
        ["final_action", sa.text("decided_at DESC")],
    )
    op.create_index(
        "ix_sdec_rejection_stage",
        "shadow_decisions",
        ["rejection_stage"],
        postgresql_where=sa.text("rejection_stage IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sdec_rejection_stage",  table_name="shadow_decisions")
    op.drop_index("ix_sdec_final_action",      table_name="shadow_decisions")
    op.drop_index("ix_sdec_user_coin_decided", table_name="shadow_decisions")
    op.drop_table("shadow_decisions")
