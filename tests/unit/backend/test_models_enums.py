"""모델 ENUM 타입 단위 테스트."""
from __future__ import annotations

from app.models.enums import (
    CloseReasonType, ExchangeType, HealthStatusType,
    NotificationChannelType, NotificationTypeEnum,
    OrderPurposeType, OrderSideType, OrderStatusType, OrderTypeEnum,
    PlanType, PositionStatusType, RiskProfileType,
    SignalDirectionType, SignalStatusType,
    SubscriptionStatusType, TradingModeType,
    BillingPeriodType,
)


class TestPlanType:
    def test_values(self) -> None:
        assert PlanType.FREE.value == "free"
        assert PlanType.PRO.value == "pro"
        assert PlanType.ELITE.value == "elite"

    def test_count(self) -> None:
        assert len(PlanType) == 3


class TestSignalDirectionType:
    def test_values(self) -> None:
        assert SignalDirectionType.LONG.value == "LONG"
        assert SignalDirectionType.SHORT.value == "SHORT"
        assert SignalDirectionType.HOLD.value == "HOLD"

    def test_position_only_allows_long_short(self) -> None:
        """포지션은 LONG/SHORT만 허용 — HOLD는 positions.direction에 들어갈 수 없음."""
        position_directions = {SignalDirectionType.LONG, SignalDirectionType.SHORT}
        assert SignalDirectionType.HOLD not in position_directions


class TestOrderTypeEnum:
    def test_all_values(self) -> None:
        values = {e.value for e in OrderTypeEnum}
        assert "market" in values
        assert "limit" in values
        assert "stop_market" in values
        assert "take_profit_market" in values
        assert "trailing_stop" in values


class TestCloseReasonType:
    def test_all_values(self) -> None:
        values = {e.value for e in CloseReasonType}
        expected = {"tp_hit", "sl_hit", "manual", "liquidated", "emergency", "dca_reversal"}
        assert values == expected


class TestNotificationTypeEnum:
    def test_trading_notifications_exist(self) -> None:
        values = {e.value for e in NotificationTypeEnum}
        assert "signal_new" in values
        assert "order_filled" in values
        assert "position_closed" in values
        assert "liquidation_warning" in values
        assert "daily_summary" in values


class TestEnumStringMixin:
    def test_plan_type_is_str(self) -> None:
        """str enum — FastAPI 직렬화 및 Pydantic 호환성."""
        assert PlanType.PRO == "pro"
        assert PlanType.FREE != "pro"

    def test_signal_direction_str(self) -> None:
        assert SignalDirectionType.LONG == "LONG"

    def test_order_side_uppercase(self) -> None:
        assert OrderSideType.BUY.value == "BUY"
        assert OrderSideType.SELL.value == "SELL"

    def test_health_status_values(self) -> None:
        assert HealthStatusType.HEALTHY.value == "healthy"
        assert HealthStatusType.DEGRADED.value == "degraded"
        assert HealthStatusType.DISCONNECTED.value == "disconnected"
