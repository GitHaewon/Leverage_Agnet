"""
Execution Engine 데이터 모델 + 티켓 빌더 테스트.

검증:
  - OrderTicket 필드 기본값
  - FilledOrder 구성
  - ExecutionResult 상태 (rejected / paper / executed)
  - build_entry_ticket: LONG→BUY/MARKET, SHORT→SELL/MARKET, reduce_only=False
  - build_tp_ticket:    LONG→SELL/TAKE_PROFIT_MARKET, reduce_only=True
  - build_sl_ticket:    LONG→SELL/STOP_MARKET, reduce_only=True
  - SHORT 방향 티켓 sides
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from agents.execution.engine import build_entry_ticket, build_sl_ticket, build_tp_ticket
from agents.execution.models import ExecutionResult, FilledOrder, OrderTicket
from agents.risk.models import ValidationResult

from tests.unit.agents._execution_fixtures import (
    make_approved_validation,
    make_rejected_validation,
    make_signal,
)


# ── OrderTicket ───────────────────────────────────────────────────────────────────

def test_order_ticket_entry_reduce_only_false():
    """MARKET 진입 주문은 reduce_only=False."""
    ticket = OrderTicket(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        price=Decimal("67450.0"),
        purpose="entry",
    )
    assert ticket.reduce_only is False


def test_order_ticket_tp_reduce_only_default_false():
    """기본 생성 시 reduce_only=False — 명시적으로 설정해야 함."""
    ticket = OrderTicket(
        symbol="BTCUSDT",
        side="SELL",
        order_type="TAKE_PROFIT_MARKET",
        quantity=Decimal("0.001"),
        price=Decimal("69200.0"),
        purpose="take_profit",
    )
    assert ticket.reduce_only is False


def test_order_ticket_fields_preserved():
    ticket = OrderTicket(
        symbol="ETHUSDT",
        side="SELL",
        order_type="STOP_MARKET",
        quantity=Decimal("0.1"),
        price=Decimal("3400.0"),
        reduce_only=True,
        purpose="stop_loss",
    )
    assert ticket.symbol == "ETHUSDT"
    assert ticket.side == "SELL"
    assert ticket.order_type == "STOP_MARKET"
    assert ticket.quantity == Decimal("0.1")
    assert ticket.price == Decimal("3400.0")
    assert ticket.reduce_only is True
    assert ticket.purpose == "stop_loss"


# ── FilledOrder ───────────────────────────────────────────────────────────────────

def test_filled_order_fields():
    now = datetime(2026, 6, 7, tzinfo=timezone.utc)
    filled = FilledOrder(
        exchange_order_id="ord-001",
        symbol="BTCUSDT",
        purpose="entry",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        avg_fill_price=Decimal("67452.10"),
        fee_usdt=Decimal("0.02698"),
        filled_at=now,
    )
    assert filled.exchange_order_id == "ord-001"
    assert filled.avg_fill_price == Decimal("67452.10")
    assert filled.fee_usdt == Decimal("0.02698")
    assert filled.filled_at == now


# ── ExecutionResult ───────────────────────────────────────────────────────────────

def test_execution_result_rejected_defaults():
    result = ExecutionResult(
        approved=False,
        executed=False,
        rejection_code="ORDER_004",
        rejection_reason="R:R 미달",
    )
    assert result.approved is False
    assert result.executed is False
    assert result.entry_order is None
    assert result.tp_sl_failed is False
    assert result.warnings == []


def test_execution_result_paper_mode():
    """approved=True, executed=False → paper 모드."""
    result = ExecutionResult(
        approved=True,
        executed=False,
        mode="paper",
        validation=make_approved_validation(),
    )
    assert result.approved is True
    assert result.executed is False
    assert result.mode == "paper"
    assert result.entry_order is None


def test_execution_result_executed_has_all_orders():
    filled = FilledOrder(
        exchange_order_id="x",
        symbol="BTCUSDT",
        purpose="entry",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        avg_fill_price=Decimal("67450"),
        fee_usdt=Decimal("0.027"),
        filled_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
    )
    result = ExecutionResult(
        approved=True,
        executed=True,
        mode="testnet",
        entry_order=filled,
        tp_order=filled,
        sl_order=filled,
    )
    assert result.entry_order is not None
    assert result.tp_order is not None
    assert result.sl_order is not None
    assert result.tp_sl_failed is False


# ── build_entry_ticket ────────────────────────────────────────────────────────────

def test_build_entry_ticket_long_side_is_buy():
    signal = make_signal(direction="LONG", symbol="BTCUSDT", entry_price=Decimal("67450"))
    val = make_approved_validation(quantity=Decimal("0.001"))
    ticket = build_entry_ticket(signal, val)
    assert ticket.side == "BUY"


def test_build_entry_ticket_short_side_is_sell():
    signal = make_signal(direction="SHORT", symbol="BTCUSDT", entry_price=Decimal("67450"))
    val = make_approved_validation(quantity=Decimal("0.001"))
    ticket = build_entry_ticket(signal, val)
    assert ticket.side == "SELL"


def test_build_entry_ticket_is_market():
    signal = make_signal()
    val = make_approved_validation()
    ticket = build_entry_ticket(signal, val)
    assert ticket.order_type == "MARKET"


def test_build_entry_ticket_not_reduce_only():
    ticket = build_entry_ticket(make_signal(), make_approved_validation())
    assert ticket.reduce_only is False


def test_build_entry_ticket_quantity_from_validation():
    val = make_approved_validation(quantity=Decimal("0.00741"))
    ticket = build_entry_ticket(make_signal(), val)
    assert ticket.quantity == Decimal("0.00741")


def test_build_entry_ticket_price_from_signal():
    signal = make_signal(entry_price=Decimal("67450"))
    ticket = build_entry_ticket(signal, make_approved_validation())
    assert ticket.price == Decimal("67450")


# ── build_tp_ticket ───────────────────────────────────────────────────────────────

def test_build_tp_ticket_long_side_is_sell():
    signal = make_signal(direction="LONG", take_profit=Decimal("69200"))
    ticket = build_tp_ticket(signal, make_approved_validation())
    assert ticket.side == "SELL"


def test_build_tp_ticket_short_side_is_buy():
    signal = make_signal(
        direction="SHORT",
        entry_price=Decimal("67450"),
        take_profit=Decimal("65700"),
        stop_loss=Decimal("68300"),
    )
    ticket = build_tp_ticket(signal, make_approved_validation())
    assert ticket.side == "BUY"


def test_build_tp_ticket_is_take_profit_market():
    ticket = build_tp_ticket(make_signal(), make_approved_validation())
    assert ticket.order_type == "TAKE_PROFIT_MARKET"


def test_build_tp_ticket_is_reduce_only():
    ticket = build_tp_ticket(make_signal(), make_approved_validation())
    assert ticket.reduce_only is True


def test_build_tp_ticket_price_from_signal():
    signal = make_signal(take_profit=Decimal("69200"))
    ticket = build_tp_ticket(signal, make_approved_validation())
    assert ticket.price == Decimal("69200")


# ── build_sl_ticket ───────────────────────────────────────────────────────────────

def test_build_sl_ticket_long_side_is_sell():
    signal = make_signal(direction="LONG", stop_loss=Decimal("66800"))
    ticket = build_sl_ticket(signal, make_approved_validation())
    assert ticket.side == "SELL"


def test_build_sl_ticket_short_side_is_buy():
    signal = make_signal(
        direction="SHORT",
        entry_price=Decimal("67450"),
        take_profit=Decimal("65700"),
        stop_loss=Decimal("68300"),
    )
    ticket = build_sl_ticket(signal, make_approved_validation())
    assert ticket.side == "BUY"


def test_build_sl_ticket_is_stop_market():
    ticket = build_sl_ticket(make_signal(), make_approved_validation())
    assert ticket.order_type == "STOP_MARKET"


def test_build_sl_ticket_is_reduce_only():
    ticket = build_sl_ticket(make_signal(), make_approved_validation())
    assert ticket.reduce_only is True


def test_build_sl_ticket_price_from_signal():
    signal = make_signal(stop_loss=Decimal("66800"))
    ticket = build_sl_ticket(signal, make_approved_validation())
    assert ticket.price == Decimal("66800")
