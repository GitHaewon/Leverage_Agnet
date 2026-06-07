"""
Alert 데이터 모델 테스트.

검증:
  - 각 이벤트 dataclass 필드 보존
  - event_type 상수 (init=False)
  - OrderFilledEvent TP/SL=None 허용
  - AlertResult success / failure 필드
"""
from __future__ import annotations

from decimal import Decimal

from agents.alert.models import (
    AlertResult,
    KillSwitchEvent,
    LiquidationRiskEvent,
    MaxDailyLossEvent,
    OrderFailedEvent,
    OrderFilledEvent,
)

from tests.unit.agents._alert_fixtures import (
    make_kill_switch,
    make_liquidation_risk,
    make_max_daily_loss,
    make_order_failed,
    make_order_filled,
    now,
)


# ── OrderFilledEvent ──────────────────────────────────────────────────────────────

def test_order_filled_event_type():
    assert make_order_filled().event_type == "order_filled"


def test_order_filled_event_type_not_in_init():
    """event_type은 init=False — 생성자 인수로 받지 않는다."""
    ev = OrderFilledEvent(
        symbol="BTCUSDT",
        direction="LONG",
        fill_price=Decimal("67452"),
        quantity=Decimal("0.001"),
        leverage=5,
        take_profit=Decimal("69200"),
        stop_loss=Decimal("66800"),
    )
    assert ev.event_type == "order_filled"


def test_order_filled_fields_preserved():
    ev = make_order_filled(
        symbol="ETHUSDT",
        direction="SHORT",
        fill_price=Decimal("3500.00"),
        quantity=Decimal("0.1"),
        leverage=3,
        take_profit=Decimal("3200.00"),
        stop_loss=Decimal("3600.00"),
    )
    assert ev.symbol == "ETHUSDT"
    assert ev.direction == "SHORT"
    assert ev.fill_price == Decimal("3500.00")
    assert ev.quantity == Decimal("0.1")
    assert ev.leverage == 3
    assert ev.take_profit == Decimal("3200.00")
    assert ev.stop_loss == Decimal("3600.00")


def test_order_filled_tp_none_allowed():
    ev = make_order_filled(take_profit=None)
    assert ev.take_profit is None


def test_order_filled_sl_none_allowed():
    ev = make_order_filled(stop_loss=None)
    assert ev.stop_loss is None


# ── OrderFailedEvent ──────────────────────────────────────────────────────────────

def test_order_failed_event_type():
    assert make_order_failed().event_type == "order_failed"


def test_order_failed_fields_preserved():
    ev = make_order_failed(
        symbol="ETHUSDT",
        direction="SHORT",
        rejection_code="ORDER_001",
        reason="일일 손실 한도 도달",
    )
    assert ev.symbol == "ETHUSDT"
    assert ev.direction == "SHORT"
    assert ev.rejection_code == "ORDER_001"
    assert ev.reason == "일일 손실 한도 도달"


# ── MaxDailyLossEvent ─────────────────────────────────────────────────────────────

def test_max_daily_loss_event_type():
    assert make_max_daily_loss().event_type == "max_daily_loss"


def test_max_daily_loss_fields_preserved():
    ts = now()
    ev = make_max_daily_loss(
        daily_loss_usdt=Decimal("300.00"),
        limit_usdt=Decimal("250.00"),
        triggered_at=ts,
    )
    assert ev.daily_loss_usdt == Decimal("300.00")
    assert ev.limit_usdt == Decimal("250.00")
    assert ev.triggered_at == ts


# ── KillSwitchEvent ───────────────────────────────────────────────────────────────

def test_kill_switch_event_type():
    assert make_kill_switch().event_type == "kill_switch"


def test_kill_switch_fields_preserved():
    ts = now()
    ev = make_kill_switch(reason="수동 발동", triggered_at=ts)
    assert ev.reason == "수동 발동"
    assert ev.triggered_at == ts


# ── LiquidationRiskEvent ──────────────────────────────────────────────────────────

def test_liquidation_risk_event_type():
    assert make_liquidation_risk().event_type == "liquidation_risk"


def test_liquidation_risk_fields_preserved():
    ev = make_liquidation_risk(
        symbol="ETHUSDT",
        direction="SHORT",
        entry_price=Decimal("3500"),
        current_price=Decimal("3800"),
        liq_price=Decimal("3900"),
        margin_ratio=Decimal("0.90"),
    )
    assert ev.symbol == "ETHUSDT"
    assert ev.direction == "SHORT"
    assert ev.entry_price == Decimal("3500")
    assert ev.current_price == Decimal("3800")
    assert ev.liq_price == Decimal("3900")
    assert ev.margin_ratio == Decimal("0.90")


# ── AlertResult ───────────────────────────────────────────────────────────────────

def test_alert_result_success():
    result = AlertResult(success=True, event_type="order_filled", chat_id="chat-001")
    assert result.success is True
    assert result.error is None


def test_alert_result_failure():
    result = AlertResult(
        success=False,
        event_type="order_failed",
        chat_id="chat-001",
        error="Telegram API timeout",
    )
    assert result.success is False
    assert result.error == "Telegram API timeout"


def test_alert_result_fields_preserved():
    result = AlertResult(success=True, event_type="kill_switch", chat_id="777")
    assert result.event_type == "kill_switch"
    assert result.chat_id == "777"
