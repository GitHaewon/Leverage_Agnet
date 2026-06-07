"""
PaperGateway 테스트.

검증:
  - MARKET BUY: avg_fill_price = price × (1 + slippage)
  - MARKET SELL: avg_fill_price = price × (1 − slippage)
  - zero slippage: avg_fill_price == price
  - TP/SL (TAKE_PROFIT_MARKET, STOP_MARKET): fill_price == stop_price (슬리피지 없음)
  - 수수료: qty × fill_price × 0.04%
  - 고유한 exchange_order_id (uuid)
  - cancel_all_orders: 페이퍼 모드에서 0 반환
  - purpose / side / order_type 그대로 보존
"""
from __future__ import annotations

import asyncio
import re
from decimal import Decimal

import pytest

from agents.execution.gateway import TAKER_FEE_RATE, PaperGateway
from agents.execution.models import OrderTicket


def _run(coro):
    return asyncio.run(coro)


def _make_ticket(
    side: str = "BUY",
    order_type: str = "MARKET",
    price: float = 67450.0,
    quantity: float = 0.001,
    purpose: str = "entry",
    reduce_only: bool = False,
) -> OrderTicket:
    return OrderTicket(
        symbol="BTCUSDT",
        side=side,
        order_type=order_type,
        quantity=Decimal(str(quantity)),
        price=Decimal(str(price)),
        reduce_only=reduce_only,
        purpose=purpose,
    )


# ── MARKET 슬리피지 ────────────────────────────────────────────────────────────────

def test_buy_market_applies_positive_slippage():
    """BUY MARKET: fill_price = price × (1 + slippage)."""
    gw = PaperGateway(slippage_bps=10)   # 0.1%
    ticket = _make_ticket(side="BUY", order_type="MARKET", price=67450.0)
    filled = _run(gw.place_order(ticket))
    expected = (Decimal("67450") * Decimal("1.001")).quantize(Decimal("0.01"))
    assert filled.avg_fill_price == expected


def test_sell_market_applies_negative_slippage():
    """SELL MARKET: fill_price = price × (1 − slippage)."""
    gw = PaperGateway(slippage_bps=10)
    ticket = _make_ticket(side="SELL", order_type="MARKET", price=66800.0)
    filled = _run(gw.place_order(ticket))
    expected = (Decimal("66800") * Decimal("0.999")).quantize(Decimal("0.01"))
    assert filled.avg_fill_price == expected


def test_zero_slippage_buy_fills_at_exact_price():
    """slippage_bps=0: fill_price == price."""
    gw = PaperGateway(slippage_bps=0)
    ticket = _make_ticket(side="BUY", order_type="MARKET", price=67450.0)
    filled = _run(gw.place_order(ticket))
    assert filled.avg_fill_price == Decimal("67450.00")


def test_zero_slippage_sell_fills_at_exact_price():
    gw = PaperGateway(slippage_bps=0)
    ticket = _make_ticket(side="SELL", order_type="MARKET", price=66800.0)
    filled = _run(gw.place_order(ticket))
    assert filled.avg_fill_price == Decimal("66800.00")


def test_default_slippage_is_5bps():
    """기본 slippage = 5 bps = 0.05%."""
    gw = PaperGateway()   # slippage_bps=5
    ticket = _make_ticket(side="BUY", order_type="MARKET", price=10000.0)
    filled = _run(gw.place_order(ticket))
    # 10000 × 1.0005 = 10005.00
    assert filled.avg_fill_price == Decimal("10005.00")


# ── TP/SL 주문 (슬리피지 없음) ────────────────────────────────────────────────────

def test_take_profit_market_fills_at_stop_price():
    """TAKE_PROFIT_MARKET: 슬리피지 없이 price 그대로."""
    gw = PaperGateway(slippage_bps=20)
    ticket = _make_ticket(
        side="SELL", order_type="TAKE_PROFIT_MARKET",
        price=69200.0, purpose="take_profit",
    )
    filled = _run(gw.place_order(ticket))
    assert filled.avg_fill_price == Decimal("69200.00")


def test_stop_market_fills_at_stop_price():
    """STOP_MARKET: 슬리피지 없이 price 그대로."""
    gw = PaperGateway(slippage_bps=20)
    ticket = _make_ticket(
        side="SELL", order_type="STOP_MARKET",
        price=66800.0, reduce_only=True, purpose="stop_loss",
    )
    filled = _run(gw.place_order(ticket))
    assert filled.avg_fill_price == Decimal("66800.00")


# ── 수수료 ────────────────────────────────────────────────────────────────────────

def test_fee_is_taker_rate_times_notional():
    """fee = qty × fill_price × TAKER_FEE_RATE."""
    gw = PaperGateway(slippage_bps=0)   # 슬리피지 없애서 계산 단순화
    ticket = _make_ticket(side="BUY", order_type="MARKET", price=67450.0, quantity=0.001)
    filled = _run(gw.place_order(ticket))
    expected_fee = (Decimal("0.001") * Decimal("67450.00") * TAKER_FEE_RATE).quantize(
        Decimal("0.00001")
    )
    assert filled.fee_usdt == expected_fee


def test_fee_larger_for_bigger_position():
    gw = PaperGateway(slippage_bps=0)
    small = _make_ticket(quantity=0.001, price=67450.0)
    large = _make_ticket(quantity=0.01, price=67450.0)
    fee_small = _run(gw.place_order(small)).fee_usdt
    fee_large = _run(gw.place_order(large)).fee_usdt
    assert fee_large > fee_small


# ── exchange_order_id 고유성 ───────────────────────────────────────────────────────

def test_each_order_has_unique_exchange_id():
    gw = PaperGateway(slippage_bps=0)
    ticket = _make_ticket()
    ids = {_run(gw.place_order(ticket)).exchange_order_id for _ in range(5)}
    assert len(ids) == 5


def test_exchange_order_id_is_uuid_format():
    gw = PaperGateway()
    filled = _run(gw.place_order(_make_ticket()))
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    assert uuid_pattern.match(filled.exchange_order_id)


# ── 필드 보존 ─────────────────────────────────────────────────────────────────────

def test_filled_order_preserves_purpose():
    gw = PaperGateway(slippage_bps=0)
    ticket = _make_ticket(purpose="stop_loss", order_type="STOP_MARKET", side="SELL")
    filled = _run(gw.place_order(ticket))
    assert filled.purpose == "stop_loss"


def test_filled_order_preserves_symbol():
    gw = PaperGateway()
    ticket = OrderTicket(
        symbol="ETHUSDT", side="BUY", order_type="MARKET",
        quantity=Decimal("0.01"), price=Decimal("3500"), purpose="entry",
    )
    filled = _run(gw.place_order(ticket))
    assert filled.symbol == "ETHUSDT"


def test_filled_order_preserves_quantity():
    gw = PaperGateway(slippage_bps=0)
    ticket = _make_ticket(quantity=0.00741)
    filled = _run(gw.place_order(ticket))
    assert filled.quantity == Decimal("0.00741")


# ── cancel_all_orders ─────────────────────────────────────────────────────────────

def test_cancel_all_orders_returns_zero():
    gw = PaperGateway()
    result = _run(gw.cancel_all_orders("BTCUSDT"))
    assert result == 0


# ── 엣지 케이스 ───────────────────────────────────────────────────────────────────

def test_slippage_not_applied_to_zero_price():
    """price=0이면 슬리피지 적용 후에도 0."""
    gw = PaperGateway(slippage_bps=10)
    ticket = _make_ticket(side="BUY", order_type="MARKET", price=0.0)
    filled = _run(gw.place_order(ticket))
    assert filled.avg_fill_price == Decimal("0.00")
