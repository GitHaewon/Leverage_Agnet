"""
RSIReversalStrategy 단위 테스트.

검증:
  - RSI 과매도 + BB 하단 → LONG
  - RSI 과매수 + BB 상단 → SHORT
  - RSI 중립 → NO_TRADE
  - BB 조건 미충족 → NO_TRADE
  - 신뢰도 단계 (RSI 깊이)
  - TP ≥ BB 중심선 (LONG), TP ≤ BB 중심선 (SHORT) — 또는 최소 R:R 보장
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.strategy.rsi_reversal import RSIReversalStrategy
from agents.strategy.models import StrategyInput

from tests.unit.agents._strategy_fixtures import (
    make_ta_result,
    make_tf_analysis,
)

PRICE = Decimal("67450.00")
COIN  = "BTC"
SYM   = "BTCUSDT"


def _inp(tf_data, tf="1h", price=PRICE):
    ta = make_ta_result(coin=COIN, symbol=SYM, analyses={tf: tf_data})
    return StrategyInput(coin=COIN, symbol=SYM, current_price=price, ta_result=ta, primary_timeframe=tf)


# ── LONG 조건 ─────────────────────────────────────────────────────────────────

def test_long_oversold_rsi_with_bb_lower():
    """RSI=28, %B=0.12 → LONG."""
    tf = make_tf_analysis(rsi=28.0, pct_b=0.12, bb_middle=68000.0, atr=300.0)
    sig = RSIReversalStrategy().evaluate(_inp(tf))
    assert sig.direction == "LONG"
    assert sig.confidence >= 0.65


def test_long_rsi_20_highest_confidence():
    """RSI=20(극단 과매도) → 신뢰도 0.78 이상."""
    tf = make_tf_analysis(rsi=20.0, pct_b=0.05, bb_middle=68500.0, atr=300.0)
    sig = RSIReversalStrategy().evaluate(_inp(tf))
    assert sig.confidence >= 0.78


def test_long_tp_at_least_bb_middle():
    """LONG TP는 BB 중심선 이상이거나 최소 R:R 2.5 보장."""
    bb_mid = 68500.0
    tf = make_tf_analysis(rsi=28.0, pct_b=0.10, bb_middle=bb_mid, atr=200.0)
    sig = RSIReversalStrategy().evaluate(_inp(tf))
    assert sig.take_profit >= Decimal(str(round(bb_mid, 2)))


def test_long_tp_minimum_rr_when_bb_close():
    """BB 중심선이 너무 가까우면 ATR 기준 최소 R:R 적용."""
    price = Decimal("67000.00")
    # BB middle이 현재가에 너무 가까움 (0.3 × ATR 이내)
    tf = make_tf_analysis(rsi=29.0, pct_b=0.15, bb_middle=67100.0, atr=500.0)
    sig = RSIReversalStrategy().evaluate(_inp(tf, price=price))
    sl_dist = float(price) - float(sig.stop_loss)
    tp_dist = float(sig.take_profit) - float(price)
    assert tp_dist / sl_dist >= 2.0


def test_long_macd_bullish_cross_boosts_confidence():
    tf_no_cross = make_tf_analysis(rsi=27.0, pct_b=0.10, bb_middle=68200.0, atr=300.0, macd_cross="neutral")
    tf_with_cross = make_tf_analysis(rsi=27.0, pct_b=0.10, bb_middle=68200.0, atr=300.0, macd_cross="bullish")
    sig_no  = RSIReversalStrategy().evaluate(_inp(tf_no_cross))
    sig_yes = RSIReversalStrategy().evaluate(_inp(tf_with_cross))
    assert sig_yes.confidence > sig_no.confidence


# ── SHORT 조건 ────────────────────────────────────────────────────────────────

def test_short_overbought_rsi_with_bb_upper():
    """RSI=72, %B=0.88 → SHORT."""
    tf = make_tf_analysis(rsi=72.0, pct_b=0.88, bb_middle=66000.0, atr=300.0)
    price = Decimal("67450.00")
    sig = RSIReversalStrategy().evaluate(_inp(tf, price=price))
    assert sig.direction == "SHORT"
    assert sig.take_profit < price
    assert sig.stop_loss > price


# ── NO_TRADE 조건 ─────────────────────────────────────────────────────────────

def test_no_trade_rsi_neutral():
    """RSI=55 → NO_TRADE."""
    tf = make_tf_analysis(rsi=55.0, pct_b=0.50, bb_middle=67500.0, atr=300.0)
    sig = RSIReversalStrategy().evaluate(_inp(tf))
    assert sig.direction == "NO_TRADE"


def test_no_trade_rsi_oversold_but_bb_not_lower():
    """RSI=28이지만 BB %B=0.60 → NO_TRADE (BB 조건 미충족)."""
    tf = make_tf_analysis(rsi=28.0, pct_b=0.60, bb_middle=68000.0, atr=300.0)
    sig = RSIReversalStrategy().evaluate(_inp(tf))
    assert sig.direction == "NO_TRADE"


def test_no_trade_missing_timeframe():
    ta = make_ta_result(COIN, SYM, analyses={})
    inp = StrategyInput(coin=COIN, symbol=SYM, current_price=PRICE, ta_result=ta)
    sig = RSIReversalStrategy().evaluate(inp)
    assert sig.direction == "NO_TRADE"
