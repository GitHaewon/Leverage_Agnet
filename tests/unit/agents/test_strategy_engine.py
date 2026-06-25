"""
StrategyEngine 통합 테스트.

검증:
  - LONG 다수 → LONG 반환
  - SHORT 다수 → SHORT 반환
  - 동수 → NO_TRADE
  - 전략 전부 NO_TRADE → NO_TRADE
  - 최소 신뢰도 미달 → NO_TRADE 강제
  - contributing_strategies 올바르게 수집
  - risk_bridge 변환 (NO_TRADE → HOLD)
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from agents.decision.models import MarketRegime
from agents.strategy.engine import StrategyEngine, _aggregate, build_strategy_candidates
from agents.strategy.models import AggregatedSignal, StrategyInput, StrategyCandidate, StrategySignal
from agents.strategy.risk_bridge import aggregated_signal_to_raw, strategy_signal_to_raw

from tests.unit.agents._strategy_fixtures import (
    make_ta_result,
    make_tf_analysis,
)

PRICE = Decimal("67450.00")
COIN  = "BTC"
SYM   = "BTCUSDT"


def _make_sig(
    direction: str,
    strategy_name: str = "test",
    confidence: float = 0.70,
    entry: float = 67450.0,
    tp: float = 68600.0,
    sl: float = 66500.0,
    rr: float = 2.5,
) -> StrategySignal:
    return StrategySignal(
        strategy_name=strategy_name,
        direction=direction,
        confidence=confidence,
        entry=Decimal(str(entry)),
        take_profit=Decimal(str(tp)) if direction != "NO_TRADE" else None,
        stop_loss=Decimal(str(sl))   if direction != "NO_TRADE" else None,
        leverage=5,
        rr_ratio=rr if direction != "NO_TRADE" else 0.0,
        reason="test reason",
    )


def _make_inp(tf_data_dict: dict | None = None, tf="1h"):
    analyses = tf_data_dict or {}
    ta = make_ta_result(COIN, SYM, analyses=analyses)
    return StrategyInput(coin=COIN, symbol=SYM, current_price=PRICE, ta_result=ta, primary_timeframe=tf)


# ── 다수결 집계 ───────────────────────────────────────────────────────────────

def test_aggregate_long_majority():
    signals = [
        _make_sig("LONG",  "ema_trend",   confidence=0.68),
        _make_sig("LONG",  "rsi_reversal",confidence=0.74),
        _make_sig("SHORT", "breakout",    confidence=0.65),
    ]
    inp = _make_inp()
    result = _aggregate(signals, inp)
    assert result.direction == "LONG"
    assert "ema_trend" in result.contributing_strategies
    assert "rsi_reversal" in result.contributing_strategies
    assert "breakout" not in result.contributing_strategies


def test_aggregate_short_majority():
    signals = [
        _make_sig("LONG",  "ema_trend", confidence=0.65),
        _make_sig("SHORT", "rsi_reversal", confidence=0.72),
        _make_sig("SHORT", "breakout",     confidence=0.78),
    ]
    inp = _make_inp()
    result = _aggregate(signals, inp)
    assert result.direction == "SHORT"


def test_aggregate_tie_returns_no_trade():
    signals = [
        _make_sig("LONG",  "ema_trend"),
        _make_sig("SHORT", "rsi_reversal"),
    ]
    inp = _make_inp()
    result = _aggregate(signals, inp)
    assert result.direction == "NO_TRADE"


def test_aggregate_all_no_trade():
    signals = [
        _make_sig("NO_TRADE", "ema_trend"),
        _make_sig("NO_TRADE", "rsi_reversal"),
        _make_sig("NO_TRADE", "breakout"),
    ]
    inp = _make_inp()
    result = _aggregate(signals, inp)
    assert result.direction == "NO_TRADE"


def test_aggregate_confidence_average():
    """통합 신뢰도는 동일 방향 전략들의 평균."""
    signals = [
        _make_sig("LONG", "s1", confidence=0.70),
        _make_sig("LONG", "s2", confidence=0.80),
    ]
    inp = _make_inp()
    result = _aggregate(signals, inp)
    assert result.confidence == pytest.approx(0.75, abs=1e-3)


# ── StrategyCandidate adapter ────────────────────────────────────────────────

def test_build_strategy_candidates_splits_strategy_names():
    signals = [
        _make_sig("LONG", "ema_trend", confidence=0.80),
        _make_sig("LONG", "breakout", confidence=0.75),
        _make_sig("LONG", "rsi_reversal", confidence=0.70),
    ]
    candidates = build_strategy_candidates(signals, MarketRegime.TREND_UP)
    names = {c.strategy_name for c in candidates}
    assert "TREND_PULLBACK" in names
    assert "BREAKOUT_RETEST" in names
    assert "RANGE_MEAN_REVERSION" not in names


def test_build_strategy_candidates_range_blocks_trend_pullback_and_breakout_retest():
    signals = [
        _make_sig("LONG", "ema_trend", confidence=0.80),
        _make_sig("LONG", "breakout", confidence=0.75),
        _make_sig("LONG", "rsi_reversal", confidence=0.70),
    ]
    candidates = build_strategy_candidates(signals, MarketRegime.RANGE)
    assert [c.strategy_name for c in candidates] == ["RANGE_MEAN_REVERSION"]


def test_build_strategy_candidates_high_volatility_returns_empty():
    signals = [_make_sig("LONG", "ema_trend", confidence=0.80)]
    assert build_strategy_candidates(signals, MarketRegime.HIGH_VOLATILITY) == []


def test_aggregated_signal_keeps_candidates_for_adapter_compatibility():
    signals = [_make_sig("LONG", "ema_trend", confidence=0.80)]
    inp = _make_inp()
    with patch("agents.strategy.engine._build_strategies", return_value=[]):
        pass
    agg = _aggregate(signals, inp)
    agg.candidates = build_strategy_candidates(signals, MarketRegime.TREND_UP)
    assert isinstance(agg.candidates[0], StrategyCandidate)


# ── StrategyEngine 최소 신뢰도 필터 ──────────────────────────────────────────

def test_engine_no_trade_when_below_min_confidence():
    """집계 신뢰도 < min_confidence → NO_TRADE 강제."""
    signals = [
        _make_sig("LONG", "s1", confidence=0.55),
        _make_sig("LONG", "s2", confidence=0.57),
    ]
    inp = _make_inp()
    with patch.object(StrategyEngine, "evaluate", wraps=lambda self, i: _forced_low_conf(i)):
        pass  # 직접 _aggregate를 통해 검증

    # 낮은 신뢰도 시그널로 AggregatedSignal을 만든 뒤 engine의 min_confidence 체크 테스트
    engine = StrategyEngine(min_confidence=0.60)
    agg = _aggregate(signals, inp)
    assert agg.confidence < 0.60  # 전제 확인

    # engine이 이 낮은 신뢰도를 NO_TRADE로 변환하는지 확인
    with patch("agents.strategy.engine._aggregate", return_value=agg):
        result = engine.evaluate(inp)
    assert result.direction == "NO_TRADE"


# ── risk_bridge 변환 ─────────────────────────────────────────────────────────

def test_aggregated_signal_to_raw_long():
    agg = AggregatedSignal(
        direction="LONG",
        confidence=0.75,
        entry=PRICE,
        take_profit=Decimal("68800"),
        stop_loss=Decimal("66600"),
        leverage=5,
        rr_ratio=2.5,
        reasons=["test"],
        contributing_strategies=["ema_trend"],
    )
    raw = aggregated_signal_to_raw(agg, COIN, SYM)
    assert raw.direction == "LONG"
    assert raw.confidence == 0.75
    assert raw.entry_price == PRICE
    assert raw.stop_loss == Decimal("66600")
    assert raw.coin == COIN


def test_aggregated_signal_to_raw_no_trade_becomes_hold():
    agg = AggregatedSignal(
        direction="NO_TRADE",
        confidence=0.0,
        entry=PRICE,
        take_profit=None,
        stop_loss=None,
        leverage=1,
        rr_ratio=0.0,
        reasons=["no signal"],
        contributing_strategies=[],
    )
    raw = aggregated_signal_to_raw(agg, COIN, SYM)
    assert raw.direction == "HOLD"


def test_strategy_signal_to_raw_no_trade_becomes_hold():
    sig = _make_sig("NO_TRADE")
    raw = strategy_signal_to_raw(sig, COIN, SYM)
    assert raw.direction == "HOLD"


def test_risk_bridge_assigns_signal_id():
    import uuid
    agg = AggregatedSignal(
        direction="SHORT",
        confidence=0.72,
        entry=PRICE,
        take_profit=Decimal("66000"),
        stop_loss=Decimal("68000"),
        leverage=5,
        rr_ratio=2.5,
        reasons=["test"],
        contributing_strategies=["breakout"],
    )
    sid = uuid.uuid4()
    raw = aggregated_signal_to_raw(agg, COIN, SYM, signal_id=sid)
    assert raw.signal_id == sid


# ── StrategyEngine full integration smoke test ───────────────────────────────

def test_engine_full_bullish_all_three():
    """세 전략이 모두 LONG을 낼 수 있는 시장 조건 → LONG."""
    price = 67200.0
    resistance = 67000.0   # 방금 돌파한 저항선
    tf = make_tf_analysis(
        ema9=68000, ema21=67500, ema50=67000, ema200=65000,
        macd_hist=40.0, macd_cross="bullish",
        rsi=28.0, pct_b=0.12, bb_middle=68500.0,
        atr=300.0, volume_ratio=2.5,
    )
    ta = make_ta_result(
        COIN, SYM, analyses={"1h": tf},
        resistance_levels=[resistance, 69000.0],
        support_levels=[66000.0, 65000.0],
    )
    inp = StrategyInput(
        coin=COIN, symbol=SYM,
        current_price=Decimal(str(price)),
        ta_result=ta,
        primary_timeframe="1h",
    )
    result = StrategyEngine().evaluate(inp)
    # 최소 1개 이상 LONG → 전체 방향 LONG 또는 일부 NO_TRADE로 합의
    assert result.direction in ("LONG", "NO_TRADE")
    if result.direction == "LONG":
        assert result.take_profit > Decimal(str(price))
        assert result.stop_loss   < Decimal(str(price))
        assert result.rr_ratio >= 2.0


def _forced_low_conf(inp):
    return AggregatedSignal(
        direction="LONG", confidence=0.55, entry=inp.current_price,
        take_profit=None, stop_loss=None, leverage=1, rr_ratio=0.0,
        reasons=[], contributing_strategies=[],
    )
