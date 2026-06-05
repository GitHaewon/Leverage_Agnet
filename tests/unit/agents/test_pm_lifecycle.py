"""
Position Manager — 생명주기 테스트.

검증:
  - open_position: 필드 초기화, 청산가 계산, 수수료
  - close_position: PnL(LONG 수익/손실, SHORT 수익/손실), 상태 변경
  - partial_close: 수량/증거금 감소, is_partial=True, 잔여 포지션 open 유지
  - 손절 없는 오픈 금지 (assert)
  - 이미 청산된 포지션 재청산 금지
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.position_manager.lifecycle import (
    _calc_liquidation_price,
    close_position,
    open_position,
    partial_close,
)
from agents.position_manager.models import TAKER_FEE_RATE
from agents.risk.models import ValidationResult

from tests.unit.agents._pm_fixtures import make_position, make_signal, make_validation


# ── open_position ─────────────────────────────────────────────────────────────

def test_open_long_creates_correct_state():
    sig = make_signal(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    val = make_validation(qty=0.01, leverage=5, margin=134.0, max_loss=10.0)
    result = open_position("user-1", sig, val)

    pos = result.position
    assert pos.direction == "LONG"
    assert pos.entry_price == Decimal("67000.0")
    assert pos.take_profit == Decimal("70000.0")
    assert pos.stop_loss == Decimal("66000.0")
    assert pos.quantity == Decimal("0.01")
    assert pos.leverage == 5
    assert pos.status == "open"
    assert pos.dca_count == 0
    assert pos.realized_pnl == Decimal("0")
    assert pos.user_id == "user-1"


def test_open_calculates_entry_fee():
    sig = make_signal(entry=67000.0)
    val = make_validation(qty=0.01)
    result = open_position("u", sig, val)
    # entry_fee = qty × entry × fee_rate = 0.01 × 67000 × 0.0004 = 0.268
    expected = Decimal("0.01") * Decimal("67000") * TAKER_FEE_RATE
    assert result.entry_fee == expected.quantize(Decimal("0.0001"))


def test_open_long_liquidation_price_below_entry():
    sig = make_signal(direction="LONG", entry=67000.0, leverage=5)
    val = make_validation(leverage=5)
    result = open_position("u", sig, val)
    assert result.position.liquidation_price < Decimal("67000.0")


def test_open_short_liquidation_price_above_entry():
    sig = make_signal(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0, leverage=5)
    val = make_validation(leverage=5)
    result = open_position("u", sig, val)
    assert result.position.liquidation_price > Decimal("67000.0")


def test_open_rejected_validation_raises():
    sig = make_signal()
    val = ValidationResult.reject("TEST", "test rejection")
    with pytest.raises(AssertionError):
        open_position("u", sig, val)


def test_open_no_sl_raises():
    from agents.risk.models import RawSignal
    import uuid
    sig = RawSignal(
        direction="LONG", coin="BTC", symbol="BTCUSDT",
        confidence=0.7, entry_price=Decimal("67000"),
        take_profit=Decimal("70000"), stop_loss=None,  # SL 없음
        leverage=5, signal_id=uuid.uuid4(),
    )
    val = make_validation()
    with pytest.raises(AssertionError):
        open_position("u", sig, val)


# ── close_position (LONG) ─────────────────────────────────────────────────────

def test_close_long_profit():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.01, margin=134.0)
    result = close_position(pos, Decimal("70000"), "tp_hit")

    assert result.close_reason == "tp_hit"
    assert result.gross_pnl > 0
    assert result.net_pnl > 0
    assert result.is_partial is False
    assert result.position.status == "closed"
    assert result.position.closed_at is not None
    # gross = (70000 - 67000) × 0.01 = 30
    assert result.gross_pnl == Decimal("30.00")


def test_close_long_loss():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.01, margin=134.0)
    result = close_position(pos, Decimal("66000"), "sl_hit")

    assert result.gross_pnl < 0
    assert result.net_pnl < 0
    # gross = (66000 - 67000) × 0.01 = -10
    assert result.gross_pnl == Decimal("-10.00")


def test_close_short_profit():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0, qty=0.01)
    result = close_position(pos, Decimal("64000"), "tp_hit")

    assert result.gross_pnl > 0
    # gross = (67000 - 64000) × 0.01 = 30
    assert result.gross_pnl == Decimal("30.00")


def test_close_short_loss():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0, qty=0.01)
    result = close_position(pos, Decimal("68000"), "sl_hit")

    assert result.gross_pnl < 0


def test_close_net_pnl_deducts_fee():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.01)
    result = close_position(pos, Decimal("70000"), "tp_hit")
    expected_fee = Decimal("0.01") * Decimal("70000") * TAKER_FEE_RATE
    assert result.gross_pnl - result.fee == result.net_pnl


def test_close_already_closed_raises():
    pos = make_position(status="closed")
    with pytest.raises(AssertionError):
        close_position(pos, Decimal("70000"), "tp_hit")


# ── partial_close ─────────────────────────────────────────────────────────────

def test_partial_close_50pct_reduces_quantity():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.02, margin=268.0)
    result = partial_close(pos, Decimal("68000"), ratio=0.5)

    assert result.is_partial is True
    assert result.closed_quantity == Decimal("0.010")
    assert pos.quantity == Decimal("0.010")  # 잔여
    assert pos.status == "partially_closed"


def test_partial_close_reduces_margin():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.02, margin=268.0)
    partial_close(pos, Decimal("68000"), ratio=0.5)
    assert pos.margin_used == pytest.approx(float(Decimal("268.0") * Decimal("0.5")), abs=0.01)


def test_partial_close_accumulates_realized_pnl():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.02, margin=268.0)
    result = partial_close(pos, Decimal("69000"), ratio=0.5)
    assert pos.realized_pnl == result.net_pnl


def test_partial_close_invalid_ratio_raises():
    pos = make_position()
    with pytest.raises(ValueError):
        partial_close(pos, Decimal("68000"), ratio=1.0)
    with pytest.raises(ValueError):
        partial_close(pos, Decimal("68000"), ratio=0.0)


# ── liquidation price formula ─────────────────────────────────────────────────

def test_liquidation_price_long_decreases_with_higher_leverage():
    entry = Decimal("67000")
    liq5 = _calc_liquidation_price("LONG", entry, 5)
    liq10 = _calc_liquidation_price("LONG", entry, 10)
    # 레버리지 높을수록 청산가는 entry에 더 가까워짐
    assert liq10 > liq5


def test_liquidation_price_short_increases_with_higher_leverage():
    entry = Decimal("67000")
    liq5 = _calc_liquidation_price("SHORT", entry, 5)
    liq10 = _calc_liquidation_price("SHORT", entry, 10)
    assert liq10 < liq5
