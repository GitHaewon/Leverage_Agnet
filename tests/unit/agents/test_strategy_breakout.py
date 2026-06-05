"""
BreakoutStrategy 단위 테스트.

검증:
  - 저항선 돌파 + 거래량 → LONG
  - 지지선 하향돌파 + 거래량 → SHORT
  - 거래량 부족 → NO_TRADE
  - 돌파 레벨 없음 → NO_TRADE
  - 다음 레벨 있을 때 TP 사용
  - 최소 R:R 2.0 보장
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.strategy.breakout import (
    BreakoutStrategy,
    _find_broken_level_below,
    _find_broken_level_above,
    _find_next_level_above,
    _find_next_level_below,
)
from agents.strategy.models import StrategyInput

from tests.unit.agents._strategy_fixtures import (
    make_ta_result,
    make_tf_analysis,
)

COIN = "BTC"
SYM  = "BTCUSDT"


def _inp(tf_data, price, resistances=None, supports=None, tf="1h"):
    ta = make_ta_result(
        coin=COIN, symbol=SYM, analyses={tf: tf_data},
        resistance_levels=resistances or [],
        support_levels=supports or [],
    )
    return StrategyInput(
        coin=COIN, symbol=SYM,
        current_price=Decimal(str(price)),
        ta_result=ta,
        primary_timeframe=tf,
    )


# ── LONG 돌파 ─────────────────────────────────────────────────────────────────

def test_long_breakout_above_resistance():
    """현재가가 저항선 바로 위 → LONG."""
    resistance = 67000.0
    price = 67300.0   # resistance + 0.45% (< 2% 임계)
    tf = make_tf_analysis(atr=300.0, volume_ratio=2.0)
    sig = BreakoutStrategy().evaluate(
        _inp(tf, price, resistances=[resistance, 69000.0])
    )
    assert sig.direction == "LONG"
    assert sig.stop_loss < Decimal(str(price))
    assert sig.take_profit > Decimal(str(price))
    assert sig.rr_ratio >= 2.0


def test_long_breakout_uses_next_resistance_as_tp():
    """다음 저항선이 있으면 TP로 사용 (최소 R:R 보장)."""
    resistance = 67000.0
    next_res    = 69500.0    # 다음 저항 (넉넉히 멀다)
    price = 67200.0
    tf = make_tf_analysis(atr=200.0, volume_ratio=2.5)
    sig = BreakoutStrategy().evaluate(
        _inp(tf, price, resistances=[resistance, next_res])
    )
    assert sig.direction == "LONG"
    # TP는 다음 저항선 이상이어야 함
    assert float(sig.take_profit) >= next_res


# ── SHORT 돌파 ────────────────────────────────────────────────────────────────

def test_short_breakout_below_support():
    """현재가가 지지선 바로 아래 → SHORT."""
    support = 67000.0
    price   = 66800.0   # support - 0.3% (< 2% 임계)
    tf = make_tf_analysis(atr=250.0, volume_ratio=1.8)
    sig = BreakoutStrategy().evaluate(
        _inp(tf, price, supports=[support, 65000.0])
    )
    assert sig.direction == "SHORT"
    assert sig.stop_loss > Decimal(str(price))
    assert sig.take_profit < Decimal(str(price))


# ── NO_TRADE 조건 ─────────────────────────────────────────────────────────────

def test_no_trade_insufficient_volume():
    """거래량 비율 < 1.5 → NO_TRADE."""
    tf = make_tf_analysis(atr=300.0, volume_ratio=1.2)  # 부족
    sig = BreakoutStrategy().evaluate(
        _inp(tf, 67300.0, resistances=[67000.0])
    )
    assert sig.direction == "NO_TRADE"


def test_no_trade_no_breakout_level():
    """돌파 레벨 없음 → NO_TRADE."""
    price = 67000.0
    tf = make_tf_analysis(atr=300.0, volume_ratio=2.0)
    sig = BreakoutStrategy().evaluate(
        _inp(tf, price, resistances=[70000.0], supports=[64000.0])
    )
    assert sig.direction == "NO_TRADE"


def test_no_trade_missing_timeframe():
    ta = make_ta_result(COIN, SYM, analyses={})
    inp = StrategyInput(coin=COIN, symbol=SYM, current_price=Decimal("67000"), ta_result=ta)
    assert BreakoutStrategy().evaluate(inp).direction == "NO_TRADE"


# ── 헬퍼 함수 직접 테스트 ─────────────────────────────────────────────────────

def test_find_broken_level_below_returns_nearest():
    levels = [65000.0, 66500.0, 67000.0, 70000.0]
    price  = 67200.0
    result = _find_broken_level_below(price, levels, 0.02)
    assert result == pytest.approx(67000.0)   # 67200 * 0.98 = 65856 이상이고 67200 미만


def test_find_broken_level_below_none_when_far():
    levels = [64000.0]
    price  = 67000.0
    # 64000 < 67000 × 0.98 = 65660 → 범위 밖
    assert _find_broken_level_below(price, levels, 0.02) is None


def test_find_broken_level_above_returns_nearest():
    levels = [67500.0, 68000.0, 70000.0]
    price  = 67400.0
    result = _find_broken_level_above(price, levels, 0.02)
    assert result == pytest.approx(67500.0)


def test_find_next_level_above():
    levels = [65000.0, 67000.0, 69000.0]
    assert _find_next_level_above(67200.0, levels) == pytest.approx(69000.0)


def test_find_next_level_below():
    levels = [65000.0, 66000.0, 67500.0]
    assert _find_next_level_below(67200.0, levels) == pytest.approx(66000.0)
