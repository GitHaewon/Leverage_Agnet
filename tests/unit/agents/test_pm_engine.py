"""
PositionManagerEngine 통합 테스트.

검증:
  - engine.open() → OpenResult
  - engine.close() → CloseResult (status=closed)
  - engine.partial_close() → CloseResult (status=partially_closed)
  - engine.dca() → DCAResult (avg entry 갱신)
  - engine.check_dca() → DCAEligibility 거부 (방향 다름)
  - engine.update_sl() → TPSLUpdate
  - engine.update_tp() → TPSLUpdate
  - engine.move_to_breakeven() → TPSLUpdate or None
  - engine.tick() TP 도달 → tp_sl_status="tp_hit", CloseResult, liq_check.action="none"
  - engine.tick() SL 도달 → tp_sl_status="sl_hit"
  - engine.tick() 청산 위험 → liq_check.action in ("warning","partial_close","full_close")
  - engine.tick() 정상 → tp_sl_status=None, liq_check.action="none"
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.position_manager.engine import PositionManagerEngine
from agents.position_manager.lifecycle import _calc_liquidation_price

from tests.unit.agents._pm_fixtures import (
    make_account,
    make_position,
    make_signal,
    make_validation,
)


ENGINE = PositionManagerEngine()


# ── open ──────────────────────────────────────────────────────────────────────

def test_engine_open_returns_position():
    sig = make_signal(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    val = make_validation(qty=0.01, leverage=5, margin=134.0, max_loss=10.0)
    result = ENGINE.open("user-1", sig, val)
    assert result.position.direction == "LONG"
    assert result.position.status == "open"
    assert result.entry_fee > 0


# ── close ─────────────────────────────────────────────────────────────────────

def test_engine_close_position():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    result = ENGINE.close(pos, Decimal("70000"), "tp_hit")
    assert result.position.status == "closed"
    assert result.net_pnl > 0


# ── partial_close ─────────────────────────────────────────────────────────────

def test_engine_partial_close():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.02, margin=268.0)
    result = ENGINE.partial_close(pos, Decimal("68000"), ratio=0.5)
    assert result.is_partial is True
    assert pos.status == "partially_closed"
    assert pos.quantity == Decimal("0.010")


# ── dca ───────────────────────────────────────────────────────────────────────

def test_engine_dca_updates_avg_entry():
    pos = make_position(direction="LONG", entry=67000.0, qty=0.01, original_risk=50.0)
    val = make_validation(qty=0.01, margin=134.0, max_loss=6.0)
    result = ENGINE.dca(pos, Decimal("66400"), val)
    # avg = (0.01×67000 + 0.01×66400) / 0.02 = 66700
    assert result.new_avg_entry == Decimal("66700.00")


def test_engine_check_dca_rejects_opposite_direction():
    pos = make_position(direction="LONG")
    acc = make_account()
    result = ENGINE.check_dca(
        pos, "SHORT",
        dca_entry_price=Decimal("66600"),
        dca_risk_usdt=Decimal("5"),
        current_atr=Decimal("300"),
        account=acc,
    )
    assert not result.eligible


# ── tp/sl 관리 ────────────────────────────────────────────────────────────────

def test_engine_update_sl():
    pos = make_position(direction="LONG", entry=67000.0, sl=66000.0)
    pos.current_price = Decimal("68000.0")
    update = ENGINE.update_sl(pos, Decimal("66800"), "trailing")
    assert pos.stop_loss == Decimal("66800")
    assert update.reason == "trailing"


def test_engine_update_tp():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0)
    pos.current_price = Decimal("68500.0")
    update = ENGINE.update_tp(pos, Decimal("71000"), "target_raised")
    assert pos.take_profit == Decimal("71000")


def test_engine_move_to_breakeven_profitable():
    pos = make_position(direction="LONG", entry=67000.0, sl=66000.0)
    pos.current_price = Decimal("68000.0")
    result = ENGINE.move_to_breakeven(pos, Decimal("68000.0"))
    assert result is not None
    assert pos.stop_loss > Decimal("66000.0")


def test_engine_move_to_breakeven_not_profitable():
    pos = make_position(direction="LONG", entry=67000.0, sl=66000.0)
    pos.current_price = Decimal("67010.0")
    result = ENGINE.move_to_breakeven(pos, Decimal("67010.0"))
    assert result is None


# ── tick ──────────────────────────────────────────────────────────────────────

def test_tick_tp_hit_closes_position():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0, qty=0.01)
    result = ENGINE.tick(pos, Decimal("70000"))
    assert result.tp_sl_status == "tp_hit"
    assert result.close_result is not None
    assert result.close_result.net_pnl > 0
    assert pos.status == "closed"


def test_tick_sl_hit_closes_position():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0, qty=0.01)
    result = ENGINE.tick(pos, Decimal("65500"))
    assert result.tp_sl_status == "sl_hit"
    assert result.close_result is not None
    assert result.close_result.net_pnl < 0
    assert pos.status == "closed"


def test_tick_no_trigger_returns_none_status():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0, leverage=3)
    result = ENGINE.tick(pos, Decimal("67500"))
    assert result.tp_sl_status is None
    assert result.close_result is None
    assert pos.status == "open"


def test_tick_liq_check_safe_returns_none():
    """레버리지 3배 포지션은 현재가에서 청산가가 멀어 action=none."""
    pos = make_position(direction="LONG", entry=67000.0, leverage=3)
    result = ENGINE.tick(pos, Decimal("67000"))
    assert result.liq_check.action == "none"


def test_tick_liq_check_near_liq_returns_action():
    """청산가 바로 위에서 action이 none이 아님."""
    entry = Decimal("67000")
    leverage = 10
    liq = _calc_liquidation_price("LONG", entry, leverage)
    pos = make_position(direction="LONG", entry=float(entry), leverage=leverage, tp=80000.0, sl=60000.0)
    pos.liquidation_price = liq

    # 청산가에서 1.5% 위 → partial_close 또는 full_close
    near_liq = liq * Decimal("1.015")
    result = ENGINE.tick(pos, near_liq)
    assert result.liq_check.action in ("partial_close", "full_close")


def test_tick_after_close_liq_action_is_none():
    """TP/SL 도달로 포지션 청산 후 liq_check.action은 none."""
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0, leverage=10)
    result = ENGINE.tick(pos, Decimal("70000"))
    assert result.tp_sl_status == "tp_hit"
    assert result.liq_check.action == "none"   # 이미 청산됐으므로


def test_tick_updates_current_price():
    pos = make_position(direction="LONG", entry=67000.0, tp=70000.0, sl=66000.0)
    ENGINE.tick(pos, Decimal("67500"))
    assert pos.current_price == Decimal("67500")


# ── short tick ────────────────────────────────────────────────────────────────

def test_tick_short_tp_hit():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0, qty=0.01)
    result = ENGINE.tick(pos, Decimal("64000"))
    assert result.tp_sl_status == "tp_hit"
    assert result.close_result.gross_pnl > 0


def test_tick_short_sl_hit():
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0, qty=0.01)
    result = ENGINE.tick(pos, Decimal("68500"))
    assert result.tp_sl_status == "sl_hit"
