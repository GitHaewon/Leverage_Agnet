"""DecisionEngine StrategyCandidate adapter tests."""
from __future__ import annotations

from decimal import Decimal

from agents.decision.engine import DecisionEngine
from agents.decision.models import (
    DerivativesMarketScore,
    MarketRegime,
    MarketRegimeResult,
    NewsSentimentScore,
    SignalScore,
)
from agents.strategy.models import AggregatedSignal, StrategySignal


def _sig(
    strategy_name: str,
    *,
    confidence: float,
    direction: str = "LONG",
) -> StrategySignal:
    return StrategySignal(
        strategy_name=strategy_name,
        direction=direction,  # type: ignore[arg-type]
        confidence=confidence,
        entry=Decimal("67000"),
        take_profit=Decimal("69200"),
        stop_loss=Decimal("66000"),
        leverage=5,
        rr_ratio=2.2,
        reason=f"{strategy_name} candidate",
    )


def _strategy_signal() -> AggregatedSignal:
    signals = [
        _sig("ema_trend", confidence=0.70),
        _sig("breakout", confidence=0.90),
        _sig("rsi_reversal", confidence=0.95),
    ]
    return AggregatedSignal(
        direction="LONG",
        confidence=0.80,
        entry=Decimal("67000"),
        take_profit=Decimal("69200"),
        stop_loss=Decimal("66000"),
        leverage=5,
        rr_ratio=2.2,
        reasons=["legacy aggregate"],
        contributing_strategies=["ema_trend", "breakout"],
        all_signals=signals,
    )


def _patch_scores(monkeypatch, regime: MarketRegime) -> None:
    monkeypatch.setattr(
        "agents.decision.engine.classify_market_regime",
        lambda *args, **kwargs: MarketRegimeResult(regime=regime, confidence=0.9),
    )
    monkeypatch.setattr(
        "agents.decision.engine.score_chart_signals",
        lambda *args, **kwargs: SignalScore(
            long_score=82.0,
            short_score=10.0,
            no_trade_score=5.0,
            risk_score=10.0,
        ),
    )
    monkeypatch.setattr(
        "agents.decision.engine.score_news_sentiment",
        lambda *args, **kwargs: NewsSentimentScore(
            sentiment_score=0.0,
            long_score_adjustment=0.0,
            short_score_adjustment=0.0,
            risk_score=0.0,
            no_trade_flag=False,
        ),
    )
    monkeypatch.setattr(
        "agents.decision.engine.score_derivatives_market",
        lambda *args, **kwargs: DerivativesMarketScore(
            long_score_adjustment=0.0,
            short_score_adjustment=0.0,
            risk_score=0.0,
            crowded_side="NONE",
        ),
    )


def test_decision_engine_selects_best_allowed_strategy_candidate_in_trend(monkeypatch):
    _patch_scores(monkeypatch, MarketRegime.TREND_UP)

    result = DecisionEngine().run(
        coin="BTC",
        symbol="BTCUSDT",
        market_snapshot={"current_price": 67000.0},
        technical_result=None,
        strategy_signal=_strategy_signal(),
        account_state={"available_balance": 10000},
    )

    assert [c.strategy_name for c in result.strategy_candidates] == [
        "BREAKOUT_RETEST",
        "TREND_PULLBACK",
    ]
    assert result.selected_strategy_candidate.strategy_name == "BREAKOUT_RETEST"
    assert result.candidate.strategy_name == "BREAKOUT_RETEST"


def test_decision_engine_range_filters_to_mean_reversion_candidate(monkeypatch):
    _patch_scores(monkeypatch, MarketRegime.RANGE)

    result = DecisionEngine().run(
        coin="BTC",
        symbol="BTCUSDT",
        market_snapshot={"current_price": 67000.0},
        technical_result=None,
        strategy_signal=_strategy_signal(),
        account_state={"available_balance": 10000},
    )

    assert [c.strategy_name for c in result.strategy_candidates] == [
        "RANGE_MEAN_REVERSION",
    ]
    assert result.selected_strategy_candidate.strategy_name == "RANGE_MEAN_REVERSION"


def test_decision_engine_high_volatility_generates_no_strategy_candidates(monkeypatch):
    _patch_scores(monkeypatch, MarketRegime.HIGH_VOLATILITY)

    result = DecisionEngine().run(
        coin="BTC",
        symbol="BTCUSDT",
        market_snapshot={"current_price": 67000.0},
        technical_result=None,
        strategy_signal=_strategy_signal(),
        account_state={"available_balance": 10000},
    )

    assert result.strategy_candidates == []
    assert result.selected_strategy_candidate is None
