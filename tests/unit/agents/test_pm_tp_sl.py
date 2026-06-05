"""
Position Manager — TP/SL 테스트.

검증:
  - check_tp_sl: LONG TP/SL 도달 감지
  - check_tp_sl: SHORT TP/SL 도달 감지
  - check_tp_sl: 도달 안 함 → None
  - check_tp_sl: 이미 청산된 포지션 → None
  - update_stop_loss: SL 갱신, 잘못된 방향 거부
  - update_take_profit: TP 갱신, 잘못된 방향 거부
  - move_sl_to_breakeven: 수익권이면 이동, 아직 손익분기 못 넘으면 None
  - update_tp_and_sl: TP/SL 동시 갱신
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.position_manager.tp_sl import (
    _calc_breakeven,
    check_tp_sl,
    move_sl_to_breakeven,
    update_stop_loss,
    update_take_profit,
    update_tp_and_sl,
)

from tests.unit.agents._pm_fixtures import make_position


# ── check_tp_sl ───────────────────────────────────────────────────────────────

def test_long_tp_hit():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    assert check_tp_sl(pos, Decimal("70000")) == "tp_hit"
    assert check_tp_sl(pos, Decimal("70500")) == "tp_hit"


def test_long_sl_hit():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    assert check_tp_sl(pos, Decimal("66000")) == "sl_hit"
    assert check_tp_sl(pos, Decimal("65500")) == "sl_hit"


def test_long_no_hit():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    assert check_tp_sl(pos, Decimal("68000")) is None


def test_short_tp_hit():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0)
    assert check_tp_sl(pos, Decimal("64000")) == "tp_hit"
    assert check_tp_sl(pos, Decimal("63500")) == "tp_hit"


def test_short_sl_hit():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0)
    assert check_tp_sl(pos, Decimal("68000")) == "sl_hit"
    assert check_tp_sl(pos, Decimal("68500")) == "sl_hit"


def test_short_no_hit():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0)
    assert check_tp_sl(pos, Decimal("65000")) is None


def test_closed_position_returns_none():
    pos = make_position(status="closed", direction="LONG", tp=70000.0, sl=66000.0)
    assert check_tp_sl(pos, Decimal("75000")) is None


# ── update_stop_loss ──────────────────────────────────────────────────────────

def test_update_sl_long_moves_down():
    pos = make_position(direction="LONG", entry=67000.0, sl=66000.0, current_price=68000.0)
    pos.current_price = Decimal("68000.0")
    update = update_stop_loss(pos, Decimal("66500"), "trailing")
    assert update.new_sl == Decimal("66500")
    assert pos.stop_loss == Decimal("66500")
    assert update.field_updated == "sl"
    assert update.reason == "trailing"


def test_update_sl_long_above_current_price_raises():
    pos = make_position(direction="LONG", entry=67000.0, sl=66000.0)
    pos.current_price = Decimal("67000.0")
    with pytest.raises(ValueError, match="아래여야"):
        update_stop_loss(pos, Decimal("68000"), "invalid")


def test_update_sl_short_below_current_price_raises():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0)
    pos.current_price = Decimal("67000.0")
    with pytest.raises(ValueError, match="위여야"):
        update_stop_loss(pos, Decimal("66000"), "invalid")


def test_update_sl_closed_position_raises():
    pos = make_position(status="closed")
    with pytest.raises(AssertionError):
        update_stop_loss(pos, Decimal("66000"), "test")


# ── update_take_profit ────────────────────────────────────────────────────────

def test_update_tp_long():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0)
    pos.current_price = Decimal("68000.0")
    update = update_take_profit(pos, Decimal("71000"), "target_raised")
    assert pos.take_profit == Decimal("71000")
    assert update.old_tp == Decimal("70000.0")
    assert update.field_updated == "tp"


def test_update_tp_long_below_current_raises():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0)
    pos.current_price = Decimal("68000.0")
    with pytest.raises(ValueError, match="위여야"):
        update_take_profit(pos, Decimal("67500"), "invalid")


def test_update_tp_short():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0)
    pos.current_price = Decimal("66000.0")
    update = update_take_profit(pos, Decimal("63000"), "target_lowered")
    assert pos.take_profit == Decimal("63000")


# ── move_sl_to_breakeven ──────────────────────────────────────────────────────

def test_breakeven_long_calculation():
    pos = make_position(direction="LONG", entry=67000.0)
    be = _calc_breakeven(pos, pos.take_profit.__class__("0.0004"))
    # breakeven = 67000 × (1 + 2×0.0004) = 67000 × 1.0008 = 67053.6
    assert float(be) == pytest.approx(67000.0 * 1.0008, rel=1e-5)


def test_breakeven_short_calculation():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0)
    from agents.position_manager.models import TAKER_FEE_RATE
    be = _calc_breakeven(pos, TAKER_FEE_RATE)
    assert float(be) == pytest.approx(67000.0 * (1 - 2 * 0.0004), rel=1e-5)


def test_move_sl_to_breakeven_when_profitable():
    """현재가가 손익분기점 위 → SL 이동."""
    pos = make_position(direction="LONG", entry=67000.0, sl=66000.0)
    current = Decimal("68000.0")   # 충분히 수익권
    pos.current_price = current
    result = move_sl_to_breakeven(pos, current)
    assert result is not None
    assert result.new_sl > Decimal("66000.0")  # 기존 SL보다 높아짐
    assert pos.stop_loss == result.new_sl


def test_move_sl_to_breakeven_returns_none_if_not_profitable():
    """현재가가 손익분기점 아래 → None 반환."""
    pos = make_position(direction="LONG", entry=67000.0, sl=66000.0)
    current = Decimal("67010.0")  # 손익분기점(67053.6) 못 넘음
    result = move_sl_to_breakeven(pos, current)
    assert result is None


def test_move_sl_to_breakeven_returns_none_if_sl_already_above():
    """이미 손익분기보다 높은 SL → None 반환."""
    pos = make_position(direction="LONG", entry=67000.0, sl=67100.0)  # 이미 BE 위
    pos.current_price = Decimal("68000.0")
    result = move_sl_to_breakeven(pos, Decimal("68000.0"))
    assert result is None


def test_move_sl_to_breakeven_short():
    """SHORT: 현재가가 손익분기 아래 → SL 이동."""
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0)
    current = Decimal("66000.0")
    pos.current_price = current
    result = move_sl_to_breakeven(pos, current)
    assert result is not None
    # SHORT breakeven ≈ 67000 × 0.9992 ≈ 66946.4 → SL 아래로 이동
    assert result.new_sl < Decimal("68000.0")


# ── update_tp_and_sl ─────────────────────────────────────────────────────────

def test_update_tp_and_sl_both():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    pos.current_price = Decimal("67500.0")
    update = update_tp_and_sl(pos, Decimal("71000"), Decimal("66500"), "rebalance")
    assert update.field_updated == "both"
    assert pos.take_profit == Decimal("71000")
    assert pos.stop_loss == Decimal("66500")


def test_update_tp_and_sl_tp_only():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    pos.current_price = Decimal("67500.0")
    update = update_tp_and_sl(pos, Decimal("71000"), None, "tp_only")
    assert update.field_updated == "tp"
    assert pos.stop_loss == Decimal("66000.0")  # 변경 안 됨
