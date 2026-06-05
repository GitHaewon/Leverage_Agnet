"""
모델 제약조건 및 비즈니스 규칙 단위 테스트.

SQLite는 GENERATED COLUMNS, PostgreSQL INET 등을 지원하지 않으므로
DB 레벨 제약조건은 통합 테스트에서 검증하고,
여기서는 Python 레벨 로직과 모델 메타데이터를 검증한다.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import (
    CloseReasonType, ExchangeType, HealthStatusType, OrderPurposeType,
    OrderSideType, OrderStatusType, OrderTypeEnum, PlanType,
    PositionStatusType, RiskProfileType, SignalDirectionType, SignalStatusType,
    TradingModeType, NotificationTypeEnum, NotificationChannelType,
)


class TestUserModelMeta:
    def test_table_name(self) -> None:
        from app.models.user import User
        assert User.__tablename__ == "users"

    def test_has_soft_delete(self) -> None:
        from app.models.user import User
        assert hasattr(User, "deleted_at")

    def test_has_timestamps(self) -> None:
        from app.models.user import User
        assert hasattr(User, "created_at")
        assert hasattr(User, "updated_at")

    def test_plan_column_exists(self) -> None:
        from app.models.user import User
        assert hasattr(User, "plan")

    def test_2fa_columns_exist(self) -> None:
        from app.models.user import User
        assert hasattr(User, "is_2fa_enabled")
        assert hasattr(User, "totp_secret_encrypted")
        assert hasattr(User, "totp_backup_codes")


class TestSignalModelMeta:
    def test_table_name(self) -> None:
        from app.models.signal import Signal
        assert Signal.__tablename__ == "signals"

    def test_no_updated_at(self) -> None:
        """시그널은 불변 — updated_at 없음."""
        from app.models.signal import Signal
        assert not hasattr(Signal, "updated_at")

    def test_has_agent_scores(self) -> None:
        from app.models.signal import Signal
        assert hasattr(Signal, "technical_score")
        assert hasattr(Signal, "sentiment_score")
        assert hasattr(Signal, "market_score")

    def test_has_reasons_array(self) -> None:
        from app.models.signal import Signal
        assert hasattr(Signal, "reasons")


class TestPositionModelMeta:
    def test_table_name(self) -> None:
        from app.models.position import Position
        assert Position.__tablename__ == "positions"

    def test_stop_loss_column_exists(self) -> None:
        """stop_loss 컬럼 존재 확인 — nullable=False는 통합 테스트에서 검증."""
        from app.models.position import Position
        assert hasattr(Position, "stop_loss")

    def test_has_opened_at_not_created_at(self) -> None:
        """포지션은 created_at 대신 opened_at 사용."""
        from app.models.position import Position
        assert hasattr(Position, "opened_at")
        assert not hasattr(Position, "created_at")

    def test_is_ai_trade_exists(self) -> None:
        from app.models.position import Position
        assert hasattr(Position, "is_ai_trade")


class TestOrderModelMeta:
    def test_table_name(self) -> None:
        from app.models.order import Order
        assert Order.__tablename__ == "orders"

    def test_remaining_quantity_computed(self) -> None:
        """remaining_quantity가 Computed 컬럼인지 확인."""
        from app.models.order import Order
        from sqlalchemy import Computed
        col = Order.__table__.c["remaining_quantity"]
        assert col.computed is not None

    def test_has_client_order_id(self) -> None:
        from app.models.order import Order
        assert hasattr(Order, "client_order_id")

    def test_has_retry_fields(self) -> None:
        from app.models.order import Order
        assert hasattr(Order, "retry_count")
        assert hasattr(Order, "max_retries")
        assert hasattr(Order, "last_retry_at")


class TestTradeLogModelMeta:
    def test_table_name(self) -> None:
        from app.models.trade_log import TradeLog
        assert TradeLog.__tablename__ == "trade_logs"

    def test_net_pnl_computed(self) -> None:
        """net_pnl이 GENERATED ALWAYS AS 컬럼인지 확인."""
        from app.models.trade_log import TradeLog
        col = TradeLog.__table__.c["net_pnl"]
        assert col.computed is not None

    def test_has_signal_snapshot_fields(self) -> None:
        from app.models.trade_log import TradeLog
        for field in ["signal_confidence", "signal_entry_price", "signal_tp",
                      "signal_sl", "signal_rr_ratio"]:
            assert hasattr(TradeLog, field), f"Missing: {field}"

    def test_no_updated_at(self) -> None:
        """거래 로그는 불변 — updated_at 없음."""
        from app.models.trade_log import TradeLog
        assert not hasattr(TradeLog, "updated_at")


class TestAgentDecisionModelMeta:
    def test_table_name(self) -> None:
        from app.models.agent_decision import AgentDecision
        assert AgentDecision.__tablename__ == "agent_decisions"

    def test_has_jsonb_fields(self) -> None:
        from app.models.agent_decision import AgentDecision
        assert hasattr(AgentDecision, "input_data")
        assert hasattr(AgentDecision, "output_data")

    def test_valid_agent_names_constant(self) -> None:
        from app.models.agent_decision import VALID_AGENT_NAMES
        assert "technical_analyst" in VALID_AGENT_NAMES
        assert "sentiment" in VALID_AGENT_NAMES
        assert "market_structure" in VALID_AGENT_NAMES
        assert "synthesis" in VALID_AGENT_NAMES
        assert "risk_manager" in VALID_AGENT_NAMES
        assert len(VALID_AGENT_NAMES) == 5

    def test_has_cost_tracking(self) -> None:
        from app.models.agent_decision import AgentDecision
        assert hasattr(AgentDecision, "api_cost_usd")
        assert hasattr(AgentDecision, "tokens_input")
        assert hasattr(AgentDecision, "tokens_output")


class TestExchangeAccountModelMeta:
    def test_table_name(self) -> None:
        from app.models.exchange_account import ExchangeAccount
        assert ExchangeAccount.__tablename__ == "exchange_accounts"

    def test_has_encrypted_fields(self) -> None:
        from app.models.exchange_account import ExchangeAccount
        assert hasattr(ExchangeAccount, "encrypted_api_key")
        assert hasattr(ExchangeAccount, "encrypted_api_secret")
        assert hasattr(ExchangeAccount, "encryption_iv")

    def test_has_soft_delete(self) -> None:
        from app.models.exchange_account import ExchangeAccount
        assert hasattr(ExchangeAccount, "deleted_at")

    def test_has_key_fingerprint(self) -> None:
        """UI 표시용 마지막 4자리."""
        from app.models.exchange_account import ExchangeAccount
        assert hasattr(ExchangeAccount, "key_fingerprint")


class TestAuditLogModelMeta:
    def test_table_name(self) -> None:
        from app.models.audit_log import AuditLog
        assert AuditLog.__tablename__ == "audit_logs"

    def test_no_updated_at(self) -> None:
        """감사 로그는 append-only — updated_at 없음."""
        from app.models.audit_log import AuditLog
        assert not hasattr(AuditLog, "updated_at")

    def test_user_id_nullable(self) -> None:
        """삭제된 계정 로그는 user_id=NULL 허용."""
        from app.models.audit_log import AuditLog
        col = AuditLog.__table__.c["user_id"]
        assert col.nullable is True


class TestOHLCVModelMeta:
    def test_table_name(self) -> None:
        from app.models.ohlcv import OHLCV
        assert OHLCV.__tablename__ == "ohlcv"

    def test_no_uuid_pk(self) -> None:
        """TimescaleDB 테이블 — UUID PK 없음, 복합 PK 사용."""
        from app.models.ohlcv import OHLCV
        assert not hasattr(OHLCV, "id")

    def test_composite_pk_columns(self) -> None:
        from app.models.ohlcv import OHLCV
        pk_cols = {c.name for c in OHLCV.__table__.primary_key}
        assert pk_cols == {"time", "coin", "interval"}

    def test_ohlcv_columns_exist(self) -> None:
        from app.models.ohlcv import OHLCV
        for col in ["open", "high", "low", "close", "volume"]:
            assert hasattr(OHLCV, col)


class TestModelRelationships:
    def test_user_has_subscription_rel(self) -> None:
        from app.models.user import User
        assert hasattr(User, "subscription")
        assert hasattr(User, "settings")
        assert hasattr(User, "exchange_accounts")
        assert hasattr(User, "positions")
        assert hasattr(User, "notifications")

    def test_signal_has_agent_decisions_rel(self) -> None:
        from app.models.signal import Signal
        assert hasattr(Signal, "agent_decisions")
        assert hasattr(Signal, "positions")
        assert hasattr(Signal, "trade_logs")

    def test_position_has_orders_and_trade_log(self) -> None:
        from app.models.position import Position
        assert hasattr(Position, "orders")
        assert hasattr(Position, "trade_log")

    def test_order_has_position_rel(self) -> None:
        from app.models.order import Order
        assert hasattr(Order, "position")

    def test_trade_log_has_signal_snapshot(self) -> None:
        from app.models.trade_log import TradeLog
        assert hasattr(TradeLog, "signal")
