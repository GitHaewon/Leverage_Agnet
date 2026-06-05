"""
Position Manager — 긴급 청산 테스트 (§10).

검증:
  - LONG: 청산가까지 거리 계산
  - SHORT: 청산가까지 거리 계산
  - distance ≤ 2%: full_close
  - distance ≤ 3%: partial_close
  - distance ≤ 5%: warning
  - distance ≤ 10%: warning
  - distance > 10%: none
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.position_manager.emergency import (
    _calc_distance,
    _distance_to_action,
    check_liquidation_distance,
)
from agents.position_manager.lifecycle import _calc_liquidation_price

from tests.unit.agents._pm_fixtures import make_position


# ── _calc_distance ────────────────────────────────────────────────────────────

def test_long_distance_formula():
    """LONG: distance = (current - liq) / current."""
    pos = make_position(direction="LONG", entry=67000.0, leverage=10)
    # liq ≈ 67000 × (1 - 1/10 + 0.004) = 67000 × 0.904 = 60568
    current = Decimal("67000.0")
    dist = _calc_distance(pos, current)
    expected = float((current - pos.liquidation_price) / current)
    assert dist == pytest.approx(expected, rel=1e-6)


def test_short_distance_formula():
    """SHORT: distance = (liq - current) / current."""
    pos = make_position(direction="SHORT", entry=67000.0, tp=64000.0, sl=68000.0, leverage=10)
    current = Decimal("67000.0")
    dist = _calc_distance(pos, current)
    expected = float((pos.liquidation_price - current) / current)
    assert dist == pytest.approx(expected, rel=1e-6)


def test_distance_zero_price_returns_zero():
    pos = make_position(direction="LONG")
    assert _calc_distance(pos, Decimal("0")) == 0.0


# ── _distance_to_action ───────────────────────────────────────────────────────

def test_action_full_close_at_2pct():
    assert _distance_to_action(0.02) == "full_close"
    assert _distance_to_action(0.01) == "full_close"
    assert _distance_to_action(0.0001) == "full_close"


def test_action_partial_close_at_3pct():
    assert _distance_to_action(0.025) == "partial_close"
    assert _distance_to_action(0.03) == "partial_close"


def test_action_warning_at_5pct():
    assert _distance_to_action(0.04) == "warning"
    assert _distance_to_action(0.05) == "warning"


def test_action_warning_at_10pct():
    assert _distance_to_action(0.07) == "warning"
    assert _distance_to_action(0.10) == "warning"


def test_action_none_above_10pct():
    assert _distance_to_action(0.11) == "none"
    assert _distance_to_action(0.50) == "none"
    assert _distance_to_action(1.0) == "none"


# ── check_liquidation_distance 통합 ──────────────────────────────────────────

def test_long_near_liquidation_triggers_full_close():
    """LONG 포지션이 청산가 1% 위 → full_close."""
    entry = Decimal("67000")
    leverage = 5
    liq = _calc_liquidation_price("LONG", entry, leverage)
    # 청산가 바로 1% 위 현재가
    current = liq * Decimal("1.01")

    pos = make_position(direction="LONG", entry=float(entry), leverage=leverage)
    pos.liquidation_price = liq

    result = check_liquidation_distance(pos, current)
    # distance ≈ 1% → full_close
    assert result.action == "full_close"
    assert result.distance_pct <= 0.02
    assert result.position_id == pos.id


def test_long_safe_distance_triggers_none():
    """LONG 포지션이 청산가와 충분히 멀면 none."""
    pos = make_position(direction="LONG", entry=67000.0, leverage=3)
    # 레버리지 3배 → 청산가 ≈ 67000 × (1 - 1/3 + 0.004) ≈ 44936
    current = Decimal("67000.0")  # 청산가 대비 50%+ 이상

    result = check_liquidation_distance(pos, current)
    assert result.action == "none"
    assert result.distance_pct > 0.10


def test_long_3pct_triggers_partial_close():
    """청산가 2~3% 위에서 partial_close."""
    entry = Decimal("67000")
    leverage = 5
    liq = _calc_liquidation_price("LONG", entry, leverage)
    # 청산가에서 2.5% 위
    current = liq * Decimal("1.025")

    pos = make_position(direction="LONG", entry=float(entry), leverage=leverage)
    pos.liquidation_price = liq

    result = check_liquidation_distance(pos, current)
    assert result.action == "partial_close"
    assert 0.02 < result.distance_pct <= 0.03


def test_short_near_liquidation_triggers_full_close():
    """SHORT 포지션이 청산가 1% 아래 → full_close."""
    entry = Decimal("67000")
    leverage = 5
    liq = _calc_liquidation_price("SHORT", entry, leverage)
    # 청산가 바로 1% 아래 현재가 (SHORT에서는 liq > current)
    current = liq * Decimal("0.99")

    pos = make_position(direction="SHORT", entry=float(entry), tp=64000.0, sl=68000.0, leverage=leverage)
    pos.liquidation_price = liq

    result = check_liquidation_distance(pos, current)
    assert result.action == "full_close"


def test_result_contains_correct_prices():
    pos = make_position(direction="LONG", entry=67000.0, leverage=5)
    current = Decimal("67000.0")
    result = check_liquidation_distance(pos, current)
    assert result.current_price == current
    assert result.liquidation_price == pos.liquidation_price
