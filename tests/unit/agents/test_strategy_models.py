"""
Strategy Engine 데이터 모델 및 헬퍼 단위 테스트.

검증:
  - confidence_to_leverage 매핑 (TRADING_RULES.md §1.4)
  - StrategySignal / AggregatedSignal 불변식
  - _build_signal R:R 계산 정확성
  - _no_trade 기본값
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.strategy.base import _build_signal, _no_trade, TARGET_RR
from agents.strategy.models import confidence_to_leverage


# ── confidence_to_leverage ────────────────────────────────────────────────────

@pytest.mark.parametrize("conf, expected_lev", [
    (0.60, 3),
    (0.65, 3),
    (0.70, 5),
    (0.79, 5),
    (0.80, 7),
    (0.89, 7),
    (0.90, 10),
    (0.94, 10),
    (0.95, 15),
    (1.00, 15),
])
def test_confidence_to_leverage(conf, expected_lev):
    assert confidence_to_leverage(conf) == expected_lev


# ── _no_trade ─────────────────────────────────────────────────────────────────

def test_no_trade_defaults():
    sig = _no_trade("test_strategy", Decimal("67450.00"), "이유")
    assert sig.direction == "NO_TRADE"
    assert sig.confidence == 0.0
    assert sig.take_profit is None
    assert sig.stop_loss is None
    assert sig.leverage == 1
    assert sig.rr_ratio == 0.0
    assert sig.entry == Decimal("67450.00")


# ── _build_signal ─────────────────────────────────────────────────────────────

def test_build_signal_long_rr():
    """LONG 시그널: TP - entry == sl_distance × rr (R:R 정확성)."""
    sig = _build_signal(
        strategy_name="test",
        direction="LONG",
        confidence=0.75,
        entry=67000.0,
        sl_distance=500.0,
        rr=2.5,
    )
    assert sig.direction == "LONG"
    assert sig.stop_loss == Decimal("66500.00")
    assert sig.take_profit == Decimal("68250.00")
    assert sig.rr_ratio == pytest.approx(2.5)


def test_build_signal_short_rr():
    """SHORT 시그널: entry - TP == sl_distance × rr."""
    sig = _build_signal(
        strategy_name="test",
        direction="SHORT",
        confidence=0.72,
        entry=67000.0,
        sl_distance=400.0,
        rr=2.5,
    )
    assert sig.direction == "SHORT"
    assert sig.stop_loss == Decimal("67400.00")
    assert sig.take_profit == Decimal("66000.00")
    assert sig.rr_ratio == pytest.approx(2.5)


def test_build_signal_leverage_from_confidence():
    sig = _build_signal("t", "LONG", 0.82, 67000.0, 300.0)
    assert sig.leverage == 7   # 0.80~0.90 → 7x


@pytest.mark.parametrize("conf, direction", [
    (0.62, "LONG"),
    (0.85, "SHORT"),
    (0.95, "LONG"),
])
def test_build_signal_rr_always_meets_minimum(conf, direction):
    """생성된 시그널의 R:R은 항상 MIN_RR(2.0) 이상이다."""
    from agents.strategy.base import MIN_RR
    sig = _build_signal("t", direction, conf, 67000.0, 600.0, rr=TARGET_RR)
    assert sig.rr_ratio >= MIN_RR


def test_build_signal_zero_sl_distance_raises():
    with pytest.raises(AssertionError):
        _build_signal("t", "LONG", 0.70, 67000.0, sl_distance=0.0)
