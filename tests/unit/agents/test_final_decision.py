"""
Final decision engine 단위 테스트.

검증 항목:
  1. Missing candidate returns HOLD
  2. Candidate HOLD returns HOLD
  3. UNKNOWN strategy returns HOLD
  4. Risk failure returns HOLD
  5. Missing AI review returns HOLD
  6. AI REJECT returns HOLD
  7. Critical contradiction returns HOLD
  8. Low AI confidence returns HOLD
  9. Expected net profit below threshold returns HOLD
  10. Valid LONG candidate + AI approve + risk pass returns LONG
  11. Valid SHORT candidate + AI approve + risk pass returns SHORT
  12. AI approve alone cannot pass if risk fails
"""
from __future__ import annotations

from decimal import Decimal

from agents.decision.final_decision import decide_final_action
from agents.decision.models import (
    AIReviewAction,
    AIReviewResult,
    FinalAction,
    RiskCheckResult,
    StrategyType,
    TradeCandidate,
)


def _candidate(**overrides) -> TradeCandidate:
    defaults = dict(
        action=FinalAction.LONG,
        coin="BTC",
        symbol="BTCUSDT",
        strategy_type=StrategyType.INTRADAY,
        expected_holding_minutes=30,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        leverage=5,
        margin_ratio=0.02,
        notional_size=Decimal("1000"),
        actual_rr=2.0,
        min_required_rr=1.5,
        expected_gross_profit=Decimal("100"),
        expected_gross_loss=Decimal("50"),
        expected_fees=Decimal("1"),
        expected_slippage_cost=Decimal("1"),
        expected_net_profit=Decimal("98"),
        expected_net_loss=Decimal("52"),
        liquidation_price=Decimal("80"),
        spread_bps=1.0,
        slippage_bps=1.0,
        reasons=[],
    )
    defaults.update(overrides)
    return TradeCandidate(**defaults)


def _review(**overrides) -> AIReviewResult:
    defaults = dict(
        review_action=AIReviewAction.APPROVE,
        confidence=0.85,
        critical_contradiction=False,
        risk_warnings=[],
        reason_summary="approved",
    )
    defaults.update(overrides)
    return AIReviewResult(**defaults)


def _risk(passed: bool = True, **overrides) -> RiskCheckResult:
    defaults = dict(
        passed=passed,
        failed_checks=[] if passed else ["TEST_FAIL"],
        warnings=[],
        risk_per_trade_pct=0.01,
        expected_net_profit=Decimal("98"),
        expected_net_loss=Decimal("52"),
    )
    defaults.update(overrides)
    return RiskCheckResult(**defaults)


def test_missing_candidate_returns_hold() -> None:
    result = decide_final_action(None, _review(), _risk())

    assert result.action == FinalAction.HOLD
    assert "후보" in result.reason


def test_candidate_hold_returns_hold() -> None:
    result = decide_final_action(_candidate(action=FinalAction.HOLD), _review(), _risk())

    assert result.action == FinalAction.HOLD
    assert "candidate.action=HOLD" in result.reason


def test_unknown_strategy_returns_hold() -> None:
    result = decide_final_action(
        _candidate(strategy_type=StrategyType.UNKNOWN),
        _review(),
        _risk(),
    )

    assert result.action == FinalAction.HOLD
    assert "UNKNOWN" in result.reason


def test_risk_failure_returns_hold() -> None:
    result = decide_final_action(
        _candidate(),
        _review(),
        _risk(False, failed_checks=["ORDER_001"]),
    )

    assert result.action == FinalAction.HOLD
    assert "RiskEngine" in result.reason


def test_missing_ai_review_returns_hold() -> None:
    result = decide_final_action(_candidate(), None, _risk())

    assert result.action == FinalAction.HOLD
    assert "AI 리뷰" in result.reason


def test_ai_reject_returns_hold() -> None:
    result = decide_final_action(
        _candidate(),
        _review(review_action=AIReviewAction.REJECT, reason_summary="bad setup"),
        _risk(),
    )

    assert result.action == FinalAction.HOLD
    assert result.reason == "bad setup"


def test_critical_contradiction_returns_hold() -> None:
    result = decide_final_action(
        _candidate(),
        _review(critical_contradiction=True),
        _risk(),
    )

    assert result.action == FinalAction.HOLD
    assert "critical_contradiction" in result.reason


def test_low_ai_confidence_returns_hold() -> None:
    result = decide_final_action(
        _candidate(),
        _review(confidence=0.65),
        _risk(),
        config={"min_ai_review_confidence": 0.70},
    )

    assert result.action == FinalAction.HOLD
    assert "confidence" in result.reason


def test_expected_net_profit_below_threshold_returns_hold() -> None:
    result = decide_final_action(
        _candidate(expected_net_profit=Decimal("0.50")),
        _review(),
        _risk(),
        config={"min_expected_net_profit": Decimal("1.00")},
    )

    assert result.action == FinalAction.HOLD
    assert "expected_net_profit" in result.reason


def test_valid_long_candidate_ai_approve_risk_pass_returns_long() -> None:
    result = decide_final_action(_candidate(action=FinalAction.LONG), _review(), _risk())

    assert result.action == FinalAction.LONG
    assert result.candidate is not None
    assert result.ai_review is not None
    assert result.risk_result is not None


def test_valid_short_candidate_ai_approve_risk_pass_returns_short() -> None:
    result = decide_final_action(_candidate(action=FinalAction.SHORT), _review(), _risk())

    assert result.action == FinalAction.SHORT
    assert "SHORT" in result.reason


def test_ai_approve_alone_cannot_pass_if_risk_fails() -> None:
    result = decide_final_action(
        _candidate(action=FinalAction.LONG),
        _review(review_action=AIReviewAction.APPROVE, confidence=0.99),
        _risk(False, failed_checks=["ORDER_001"]),
    )

    assert result.action == FinalAction.HOLD
