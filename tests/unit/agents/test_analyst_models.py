"""
AI Analyst Agent 모델 테스트.

검증:
  - MarketContext / TechnicalContext / StrategyContext 필드 보존
  - StrategyContext 기본값 (중립)
  - AnalysisDecision 필드
  - AnalystResult.is_actionable
  - AnalystResult.forced_hold 기본값
"""
from __future__ import annotations

from agents.analyst.models import (
    AnalysisDecision,
    AnalystResult,
    MarketContext,
    StrategyContext,
    TechnicalContext,
)

from tests.unit.agents._analyst_fixtures import (
    make_market,
    make_strategy,
    make_technical,
)


# ── MarketContext ─────────────────────────────────────────────────────────────────

def test_market_context_fields_preserved():
    ctx = make_market(coin="ETH", symbol="ETHUSDT", current_price=3500.0)
    assert ctx.coin == "ETH"
    assert ctx.symbol == "ETHUSDT"
    assert ctx.current_price == 3500.0


# ── TechnicalContext ──────────────────────────────────────────────────────────────

def test_technical_context_fields_preserved():
    ctx = make_technical(tech_score=0.5)
    assert ctx.tech_score == 0.5
    assert "rsi_1h" in ctx.indicators
    assert len(ctx.signals_fired) > 0


def test_technical_context_negative_score():
    ctx = make_technical(tech_score=-0.6)
    assert ctx.tech_score < 0


def test_technical_context_support_resistance():
    ctx = make_technical(
        support_levels=[65000.0, 64000.0],
        resistance_levels=[69000.0, 70000.0],
    )
    assert ctx.support_levels[0] == 65000.0
    assert ctx.resistance_levels[0] == 69000.0


def test_technical_context_empty_signals():
    ctx = make_technical(signals_fired=[])
    assert ctx.signals_fired == []


# ── StrategyContext ───────────────────────────────────────────────────────────────

def test_strategy_context_fields_preserved():
    ctx = make_strategy(sentiment_score=-0.31, fear_greed_index=42)
    assert ctx.sentiment_score == -0.31
    assert ctx.fear_greed_index == 42


def test_strategy_context_default_neutral():
    """기본값: 모든 점수 0, 중립 레이블."""
    ctx = StrategyContext()
    assert ctx.sentiment_score == 0.0
    assert ctx.market_score == 0.0
    assert ctx.fear_greed_index == 50
    assert ctx.fear_greed_label == "Neutral"
    assert ctx.dominant_sentiment == "neutral"
    assert ctx.news_items == []
    assert ctx.whale_activity == "neutral"


def test_strategy_context_funding_rate():
    ctx = make_strategy(funding_rate=-0.0002)
    assert ctx.funding_rate == -0.0002


# ── AnalysisDecision ──────────────────────────────────────────────────────────────

def test_analysis_decision_long():
    dec = AnalysisDecision(decision="LONG", confidence=82, reason="강세 신호", risk_level="MEDIUM")
    assert dec.decision == "LONG"
    assert dec.confidence == 82
    assert dec.risk_level == "MEDIUM"


def test_analysis_decision_hold():
    dec = AnalysisDecision(decision="HOLD", confidence=40, reason="불확실", risk_level="HIGH")
    assert dec.decision == "HOLD"


def test_analysis_decision_short():
    dec = AnalysisDecision(decision="SHORT", confidence=75, reason="약세", risk_level="LOW")
    assert dec.decision == "SHORT"


# ── AnalystResult ─────────────────────────────────────────────────────────────────

def test_analyst_result_is_actionable_long():
    result = AnalystResult(
        decision=AnalysisDecision("LONG", 82, "강세", "MEDIUM"),
        entry_price=67450.0,
        take_profit=69200.0,
        stop_loss=66800.0,
        leverage=5,
        rr_ratio=2.71,
        raw_reasons=["reason1", "reason2", "reason3"],
    )
    assert result.is_actionable is True


def test_analyst_result_is_actionable_short():
    result = AnalystResult(
        decision=AnalysisDecision("SHORT", 78, "약세", "MEDIUM"),
        entry_price=67450.0,
        take_profit=65700.0,
        stop_loss=68300.0,
        leverage=5,
        rr_ratio=2.1,
        raw_reasons=["r1", "r2", "r3"],
    )
    assert result.is_actionable is True


def test_analyst_result_hold_not_actionable():
    result = AnalystResult(
        decision=AnalysisDecision("HOLD", 40, "불확실", "HIGH"),
        entry_price=0.0,
        take_profit=None,
        stop_loss=None,
        leverage=1,
        rr_ratio=0.0,
        raw_reasons=["불확실"],
    )
    assert result.is_actionable is False


def test_analyst_result_forced_hold_default_false():
    result = AnalystResult(
        decision=AnalysisDecision("LONG", 82, "강세", "MEDIUM"),
        entry_price=67450.0,
        take_profit=69200.0,
        stop_loss=66800.0,
        leverage=5,
        rr_ratio=2.71,
        raw_reasons=["r1", "r2", "r3"],
    )
    assert result.forced_hold is False
    assert result.hold_reason == ""


def test_analyst_result_metadata_defaults():
    result = AnalystResult(
        decision=AnalysisDecision("HOLD", 0, "test", "HIGH"),
        entry_price=0.0,
        take_profit=None,
        stop_loss=None,
        leverage=1,
        rr_ratio=0.0,
        raw_reasons=[],
    )
    assert result.model_used == ""
    assert result.tokens_input == 0
    assert result.tokens_output == 0
