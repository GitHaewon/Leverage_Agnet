"""
EMATrendStrategy 단위 테스트.

검증:
  - 완전 EMA 상승 배열 → LONG
  - 완전 EMA 하락 배열 → SHORT
  - EMA 혼재(mixed) → NO_TRADE
  - MACD 히스토그램 반대 방향 → NO_TRADE
  - 타임프레임 데이터 없음 → NO_TRADE
  - 신뢰도 보너스 (4선 정렬, MACD 크로스, 거래량)
  - TP > entry, SL < entry (LONG)
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.strategy.ema_trend import EMATrendStrategy
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

def test_long_full_bullish_alignment():
    """완전 상승 배열 + MACD 양수 → LONG."""
    tf = make_tf_analysis(
        ema9=68000, ema21=67500, ema50=67000, ema200=65000,
        macd_hist=50.0, macd_cross="neutral",
        rsi=45.0, atr=300.0,
    )
    sig = EMATrendStrategy().evaluate(_inp(tf))
    assert sig.direction == "LONG"
    assert sig.confidence >= 0.55
    assert sig.take_profit > PRICE
    assert sig.stop_loss < PRICE
    assert sig.rr_ratio >= 2.0


def test_long_with_macd_bullish_cross_boosts_confidence():
    """MACD 골든 크로스 → 신뢰도 추가."""
    tf_no_cross = make_tf_analysis(
        ema9=68000, ema21=67500, ema50=67000, ema200=65000,
        macd_hist=10.0, macd_cross="neutral",
        rsi=50.0, atr=300.0,
    )
    tf_with_cross = make_tf_analysis(
        ema9=68000, ema21=67500, ema50=67000, ema200=65000,
        macd_hist=10.0, macd_cross="bullish",
        rsi=50.0, atr=300.0,
    )
    sig_no  = EMATrendStrategy().evaluate(_inp(tf_no_cross))
    sig_yes = EMATrendStrategy().evaluate(_inp(tf_with_cross))
    assert sig_yes.confidence > sig_no.confidence


def test_long_volume_surge_boosts_confidence():
    tf_low  = make_tf_analysis(ema9=68000, ema21=67500, ema50=67000, ema200=65000,
                                macd_hist=20.0, rsi=50.0, atr=300.0, volume_ratio=0.8)
    tf_high = make_tf_analysis(ema9=68000, ema21=67500, ema50=67000, ema200=65000,
                                macd_hist=20.0, rsi=50.0, atr=300.0, volume_ratio=2.0)
    sig_low  = EMATrendStrategy().evaluate(_inp(tf_low))
    sig_high = EMATrendStrategy().evaluate(_inp(tf_high))
    assert sig_high.confidence > sig_low.confidence


# ── SHORT 조건 ────────────────────────────────────────────────────────────────

def test_short_full_bearish_alignment():
    """완전 하락 배열 + MACD 음수 → SHORT."""
    tf = make_tf_analysis(
        ema9=65000, ema21=65500, ema50=66000, ema200=68000,
        macd_hist=-40.0, macd_cross="neutral",
        rsi=55.0, atr=300.0,
    )
    price = Decimal("65200.00")
    sig = EMATrendStrategy().evaluate(_inp(tf, price=price))
    assert sig.direction == "SHORT"
    assert sig.take_profit < price
    assert sig.stop_loss > price


# ── NO_TRADE 조건 ─────────────────────────────────────────────────────────────

def test_no_trade_mixed_ema():
    """EMA 정렬 불분명 → NO_TRADE."""
    tf = make_tf_analysis(
        ema9=67000, ema21=67200, ema50=67100, ema200=67300,  # mixed
        macd_hist=20.0, rsi=50.0, atr=300.0,
    )
    sig = EMATrendStrategy().evaluate(_inp(tf))
    assert sig.direction == "NO_TRADE"


def test_no_trade_macd_contradicts_long():
    """EMA 상승이지만 MACD 히스토그램 음수 → NO_TRADE."""
    tf = make_tf_analysis(
        ema9=68000, ema21=67500, ema50=67000, ema200=65000,
        macd_hist=-30.0,  # ← 반대
        rsi=45.0, atr=300.0,
    )
    sig = EMATrendStrategy().evaluate(_inp(tf))
    assert sig.direction == "NO_TRADE"


def test_no_trade_price_below_ema50_for_long():
    """EMA 배열이 상승이지만 현재가 < EMA50 → NO_TRADE."""
    tf = make_tf_analysis(
        ema9=68000, ema21=67500, ema50=67000, ema200=65000,
        macd_hist=30.0, rsi=45.0, atr=300.0,
    )
    price = Decimal("66500.00")   # ema50(67000) 아래
    sig = EMATrendStrategy().evaluate(_inp(tf, price=price))
    assert sig.direction == "NO_TRADE"


def test_no_trade_missing_timeframe():
    """타임프레임 데이터 없음 → NO_TRADE."""
    ta = make_ta_result(COIN, SYM, analyses={})
    inp = StrategyInput(coin=COIN, symbol=SYM, current_price=PRICE, ta_result=ta, primary_timeframe="1h")
    sig = EMATrendStrategy().evaluate(inp)
    assert sig.direction == "NO_TRADE"
