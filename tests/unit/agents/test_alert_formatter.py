"""
Alert 포맷터 테스트.

검증:
  [format_order_filled]
  - 심볼 포함
  - 체결가 포함
  - 수량 포함
  - 레버리지 포함
  - TP 포함 (None이 아닐 때)
  - SL 포함 (None이 아닐 때)
  - TP=None이면 TP 라인 없음
  - SL=None이면 SL 라인 없음
  - LONG → ▲, SHORT → ▼

  [format_order_failed]
  - 심볼 포함
  - 거부 코드 포함
  - 사유 포함
  - LONG → ▲, SHORT → ▼

  [format_max_daily_loss]
  - 손실 금액 포함
  - 한도 금액 포함
  - 중단 메시지 포함
  - 발동 시각 포함

  [format_kill_switch]
  - 사유 포함
  - 발동 시각 포함
  - 중단 메시지 포함

  [format_liquidation_risk]
  - 심볼 포함
  - 진입가 포함
  - 현재가 포함
  - 청산가 포함
  - 마진 비율(%) 포함

  [format_alert 라우팅]
  - OrderFilledEvent → 주문 체결 메시지
  - OrderFailedEvent → 주문 실패 메시지
  - MaxDailyLossEvent → 일일 손실 메시지
  - KillSwitchEvent → Kill Switch 메시지
  - LiquidationRiskEvent → 청산 위험 메시지
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.alert.formatter import (
    format_alert,
    format_kill_switch,
    format_liquidation_risk,
    format_max_daily_loss,
    format_order_failed,
    format_order_filled,
)

from tests.unit.agents._alert_fixtures import (
    make_kill_switch,
    make_liquidation_risk,
    make_max_daily_loss,
    make_order_failed,
    make_order_filled,
)


# ── format_order_filled ───────────────────────────────────────────────────────────

def test_order_filled_contains_symbol():
    msg = format_order_filled(make_order_filled(symbol="ETHUSDT"))
    assert "ETHUSDT" in msg


def test_order_filled_contains_fill_price():
    msg = format_order_filled(make_order_filled(fill_price=Decimal("67452.00")))
    assert "67,452.00" in msg


def test_order_filled_contains_quantity():
    msg = format_order_filled(make_order_filled(quantity=Decimal("0.00741")))
    assert "0.00741" in msg


def test_order_filled_contains_leverage():
    msg = format_order_filled(make_order_filled(leverage=7))
    assert "7x" in msg


def test_order_filled_contains_take_profit():
    msg = format_order_filled(make_order_filled(take_profit=Decimal("69200.00")))
    assert "69,200.00" in msg


def test_order_filled_contains_stop_loss():
    msg = format_order_filled(make_order_filled(stop_loss=Decimal("66800.00")))
    assert "66,800.00" in msg


def test_order_filled_tp_none_no_tp_line():
    msg = format_order_filled(make_order_filled(take_profit=None))
    assert "TP" not in msg


def test_order_filled_sl_none_no_sl_line():
    msg = format_order_filled(make_order_filled(stop_loss=None))
    assert "SL" not in msg


def test_order_filled_long_has_up_symbol():
    msg = format_order_filled(make_order_filled(direction="LONG"))
    assert "▲" in msg


def test_order_filled_short_has_down_symbol():
    msg = format_order_filled(make_order_filled(direction="SHORT"))
    assert "▼" in msg


def test_order_filled_header_present():
    msg = format_order_filled(make_order_filled())
    assert "주문 체결" in msg


# ── format_order_failed ───────────────────────────────────────────────────────────

def test_order_failed_contains_symbol():
    msg = format_order_failed(make_order_failed(symbol="ETHUSDT"))
    assert "ETHUSDT" in msg


def test_order_failed_contains_rejection_code():
    msg = format_order_failed(make_order_failed(rejection_code="ORDER_001"))
    assert "ORDER_001" in msg


def test_order_failed_contains_reason():
    msg = format_order_failed(make_order_failed(reason="일일 손실 한도 도달"))
    assert "일일 손실 한도 도달" in msg


def test_order_failed_long_has_up_symbol():
    msg = format_order_failed(make_order_failed(direction="LONG"))
    assert "▲" in msg


def test_order_failed_short_has_down_symbol():
    msg = format_order_failed(make_order_failed(direction="SHORT"))
    assert "▼" in msg


def test_order_failed_header_present():
    msg = format_order_failed(make_order_failed())
    assert "주문 실패" in msg


# ── format_max_daily_loss ─────────────────────────────────────────────────────────

def test_max_daily_loss_contains_loss_amount():
    msg = format_max_daily_loss(make_max_daily_loss(daily_loss_usdt=Decimal("245.80")))
    assert "245.80" in msg


def test_max_daily_loss_contains_limit_amount():
    msg = format_max_daily_loss(make_max_daily_loss(limit_usdt=Decimal("200.00")))
    assert "200.00" in msg


def test_max_daily_loss_contains_stop_message():
    msg = format_max_daily_loss(make_max_daily_loss())
    assert "중단" in msg


def test_max_daily_loss_contains_triggered_at():
    msg = format_max_daily_loss(make_max_daily_loss())
    assert "2026-06-07" in msg


def test_max_daily_loss_header_present():
    msg = format_max_daily_loss(make_max_daily_loss())
    assert "일일 손실 한도" in msg


# ── format_kill_switch ────────────────────────────────────────────────────────────

def test_kill_switch_contains_reason():
    msg = format_kill_switch(make_kill_switch(reason="수동 발동"))
    assert "수동 발동" in msg


def test_kill_switch_contains_triggered_at():
    msg = format_kill_switch(make_kill_switch())
    assert "2026-06-07" in msg


def test_kill_switch_contains_stop_message():
    msg = format_kill_switch(make_kill_switch())
    assert "중단" in msg


def test_kill_switch_header_present():
    msg = format_kill_switch(make_kill_switch())
    assert "Kill Switch" in msg


# ── format_liquidation_risk ───────────────────────────────────────────────────────

def test_liquidation_risk_contains_symbol():
    msg = format_liquidation_risk(make_liquidation_risk(symbol="ETHUSDT"))
    assert "ETHUSDT" in msg


def test_liquidation_risk_contains_entry_price():
    msg = format_liquidation_risk(make_liquidation_risk(entry_price=Decimal("67000")))
    assert "67,000.00" in msg


def test_liquidation_risk_contains_current_price():
    msg = format_liquidation_risk(make_liquidation_risk(current_price=Decimal("61500")))
    assert "61,500.00" in msg


def test_liquidation_risk_contains_liq_price():
    msg = format_liquidation_risk(make_liquidation_risk(liq_price=Decimal("60200")))
    assert "60,200.00" in msg


def test_liquidation_risk_contains_margin_ratio_as_percent():
    """margin_ratio=0.85 → '85.0%'."""
    msg = format_liquidation_risk(make_liquidation_risk(margin_ratio=Decimal("0.85")))
    assert "85.0%" in msg


def test_liquidation_risk_long_has_up_symbol():
    msg = format_liquidation_risk(make_liquidation_risk(direction="LONG"))
    assert "▲" in msg


def test_liquidation_risk_short_has_down_symbol():
    msg = format_liquidation_risk(make_liquidation_risk(direction="SHORT"))
    assert "▼" in msg


def test_liquidation_risk_header_present():
    msg = format_liquidation_risk(make_liquidation_risk())
    assert "청산 위험" in msg


# ── format_alert 라우팅 ───────────────────────────────────────────────────────────

def test_format_alert_routes_order_filled():
    msg = format_alert(make_order_filled())
    assert "주문 체결" in msg


def test_format_alert_routes_order_failed():
    msg = format_alert(make_order_failed())
    assert "주문 실패" in msg


def test_format_alert_routes_max_daily_loss():
    msg = format_alert(make_max_daily_loss())
    assert "일일 손실 한도" in msg


def test_format_alert_routes_kill_switch():
    msg = format_alert(make_kill_switch())
    assert "Kill Switch" in msg


def test_format_alert_routes_liquidation_risk():
    msg = format_alert(make_liquidation_risk())
    assert "청산 위험" in msg


def test_format_alert_unknown_type_raises():
    with pytest.raises((ValueError, AttributeError)):
        format_alert(object())  # type: ignore[arg-type]
