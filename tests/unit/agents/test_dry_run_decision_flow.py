"""End-to-end dry-run coverage for the deterministic decision flow.

These tests use fakes/mocks only. They do not call AI, exchanges, or place orders.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agents.decision.candidate_generator import generate_trade_candidate
from agents.decision.models import (
    AIReviewAction,
    DerivativesMarketScore,
    FinalAction,
    MarketRegime,
    MarketRegimeResult,
    NewsSentimentScore,
    SignalScore,
    StrategySelectionResult,
    StrategyType,
    TradeCandidate,
)
from agents.decision.strategy_selector import select_strategy_type
from agents.orchestrator.logger import InMemoryLogStorage, OrchestratorLogger
from agents.orchestrator.models import PipelineInput, PipelineStatus
from agents.orchestrator.pipeline import OrchestratorPipeline
from agents.orchestrator.runner import AgentRunner
from agents.risk.engine import RiskEngine
from agents.risk.models import AccountState, UserContext

from tests.unit.agents._orchestrator_fixtures import (
    MockDecisionProvider,
    MockExecutionProvider,
    MockExecutionResult,
    MockOrder,
    MockReviewerProvider,
    MockShadowExecutionProvider,
    make_candidate,
    make_decision_result,
    make_deps,
    make_review,
    make_safe_reject_review,
)


class _RealRiskProvider:
    def __init__(self, engine: RiskEngine) -> None:
        self._engine = engine
        self.call_count = 0

    async def validate_candidate(
        self,
        candidate: TradeCandidate,
        ctx: Any,
        account: Any,
        *args: Any,
        **kwargs: Any,
    ):
        self.call_count += 1
        return await self._engine.validate_candidate(candidate, ctx, account, *args, **kwargs)


def _redis() -> AsyncMock:
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=False)
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


def _ctx(**overrides: Any) -> UserContext:
    defaults = dict(
        user_id=uuid.uuid4(),
        plan="pro",
        risk_profile="moderate",
        risk_per_trade=0.02,
        max_leverage=10,
        max_concurrent_positions=5,
        daily_loss_limit_pct=0.03,
        is_trading_active=True,
        allowed_hours_start=None,
        allowed_hours_end=None,
    )
    defaults.update(overrides)
    return UserContext(**defaults)


def _account(**overrides: Any) -> AccountState:
    defaults = dict(
        available_balance=Decimal("10000"),
        total_balance=Decimal("10000"),
        initial_balance=Decimal("10000"),
        open_positions_count=0,
        open_positions_risk_usdt=Decimal("0"),
    )
    defaults.update(overrides)
    return AccountState(**defaults)


def _input(**overrides: Any) -> PipelineInput:
    defaults = dict(
        coin="BTC",
        user_id="user_001",
        user_ctx=_ctx(),
        account_state=_account(),
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("1000"),
        consecutive_losses=0,
        open_positions=[],
        portfolio_account=None,
    )
    defaults.update(overrides)
    return PipelineInput(**defaults)


def _candidate(
    action: FinalAction = FinalAction.LONG,
    strategy_type: StrategyType = StrategyType.INTRADAY,
    *,
    actual_rr: float | None = None,
    min_required_rr: float | None = None,
    expected_holding_minutes: int | None = None,
    spread_bps: float = 1.0,
    slippage_bps: float = 1.0,
    expected_net_profit: Decimal | None = Decimal("98.40"),
    expected_net_loss: Decimal | None = Decimal("51.60"),
    liquidation_price: Decimal | None = None,
    stop_loss: Decimal | None | object = ...,
    take_profit: Decimal | None | object = ...,
) -> TradeCandidate:
    is_long = action != FinalAction.SHORT
    entry = Decimal("100")
    sl = Decimal("95") if is_long else Decimal("105")
    tp = Decimal("110") if is_long else Decimal("90")
    if stop_loss is not ...:
        sl = stop_loss
    if take_profit is not ...:
        tp = take_profit

    strategy_defaults = {
        StrategyType.SCALPING: (1.2, 5, 1.3),
        StrategyType.INTRADAY: (1.5, 30, 1.6),
        StrategyType.TREND_FOLLOWING: (2.0, 120, 2.0),
        StrategyType.BREAKOUT: (2.0, 60, 2.0),
        StrategyType.UNKNOWN: (0.0, 0, 0.0),
    }
    default_min_rr, default_minutes, default_rr = strategy_defaults[strategy_type]

    return TradeCandidate(
        action=action,
        coin="BTC",
        symbol="BTCUSDT",
        strategy_type=strategy_type,
        expected_holding_minutes=(
            default_minutes if expected_holding_minutes is None else expected_holding_minutes
        ),
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        leverage=5,
        margin_ratio=0.02,
        notional_size=Decimal("1000"),
        actual_rr=default_rr if actual_rr is None else actual_rr,
        min_required_rr=default_min_rr if min_required_rr is None else min_required_rr,
        expected_gross_profit=Decimal("100"),
        expected_gross_loss=Decimal("50"),
        expected_fees=Decimal("1"),
        expected_slippage_cost=Decimal("0.60"),
        expected_net_profit=expected_net_profit,
        expected_net_loss=expected_net_loss,
        liquidation_price=(
            Decimal("80") if is_long else Decimal("120")
        ) if liquidation_price is None else liquidation_price,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        reasons=[],
    )


def _decision(candidate: TradeCandidate, regime: MarketRegime = MarketRegime.TREND_UP):
    result = make_decision_result(candidate)
    result.regime = MarketRegimeResult(regime=regime, confidence=0.9, reasons=[])
    return result


def _pipeline_with_storage(deps) -> tuple[OrchestratorPipeline, InMemoryLogStorage]:
    storage = InMemoryLogStorage()
    return (
        OrchestratorPipeline(
            deps,
            runner=AgentRunner(max_retries=0),
            orch_logger=OrchestratorLogger(storage),
        ),
        storage,
    )


async def _run_with_real_risk(
    candidate: TradeCandidate,
    *,
    inp: PipelineInput | None = None,
    regime: MarketRegime = MarketRegime.TREND_UP,
    reviewer: MockReviewerProvider | None = None,
    execution: Any | None = None,
) -> tuple[Any, Any, InMemoryLogStorage]:
    risk = _RealRiskProvider(RiskEngine(_redis()))
    exec_provider = execution or MockExecutionProvider()
    deps = make_deps(
        decision=MockDecisionProvider(result=_decision(candidate, regime)),
        reviewer=reviewer or MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
        risk=risk,
        execution=exec_provider,
    )
    pipeline, storage = _pipeline_with_storage(deps)
    result = await pipeline.run(inp or _input())
    return result, exec_provider, storage


class TestEndToEndDryRunAllowed:
    @pytest.mark.asyncio
    async def test_strong_long_ai_approve_risk_pass_allows_execution(self) -> None:
        result, execution, storage = await _run_with_real_risk(
            _candidate(FinalAction.LONG, StrategyType.TREND_FOLLOWING)
        )

        assert result.status == PipelineStatus.COMPLETED
        assert result.step("final_decision").output.action == FinalAction.LONG
        assert execution.call_count == 1
        assert execution.last_request.final_decision.action == FinalAction.LONG
        assert storage.get_decision_logs(result.run_id)[0]["final_action"] == "LONG"

    @pytest.mark.asyncio
    async def test_strong_short_ai_approve_risk_pass_allows_execution(self) -> None:
        result, execution, storage = await _run_with_real_risk(
            _candidate(FinalAction.SHORT, StrategyType.TREND_FOLLOWING)
        )

        assert result.status == PipelineStatus.COMPLETED
        assert result.step("final_decision").output.action == FinalAction.SHORT
        assert execution.call_count == 1
        assert execution.last_request.signal.direction == "SHORT"
        assert storage.get_decision_logs(result.run_id)[0]["final_action"] == "SHORT"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("strategy_type", "rr"),
        [
            (StrategyType.SCALPING, 1.3),
            (StrategyType.INTRADAY, 1.6),
            (StrategyType.TREND_FOLLOWING, 2.0),
        ],
    )
    async def test_strategy_specific_allowed_rr_reaches_execution(
        self,
        strategy_type: StrategyType,
        rr: float,
    ) -> None:
        result, execution, _ = await _run_with_real_risk(
            _candidate(FinalAction.LONG, strategy_type, actual_rr=rr)
        )

        assert result.status == PipelineStatus.COMPLETED
        assert execution.call_count == 1


class TestEndToEndDryRunHolds:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("name", "candidate", "expected_reason"),
        [
            ("low_score", make_candidate(FinalAction.HOLD), "candidate HOLD"),
            ("conflict", make_candidate(FinalAction.HOLD), "candidate HOLD"),
            (
                "unknown_strategy",
                make_candidate(FinalAction.HOLD, StrategyType.UNKNOWN),
                "candidate HOLD",
            ),
        ],
    )
    async def test_hold_candidates_never_reach_execution(
        self,
        name: str,
        candidate: TradeCandidate,
        expected_reason: str,
    ) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            decision=MockDecisionProvider(result=make_decision_result(candidate)),
            execution=execution,
        )
        pipeline, storage = _pipeline_with_storage(deps)
        result = await pipeline.run(_input())

        assert name
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0
        log = storage.get_decision_logs(result.run_id)[0]
        assert log["final_action"] == "HOLD"
        assert log["rejection_reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_final_decision_hold_never_reaches_execution(self) -> None:
        result, execution, _ = await _run_with_real_risk(
            _candidate(FinalAction.LONG, StrategyType.TREND_FOLLOWING),
            reviewer=MockReviewerProvider(
                result=make_review(AIReviewAction.APPROVE, confidence=0.50)
            ),
        )

        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reviewer", "reason"),
        [
            (MockReviewerProvider(result=make_review(AIReviewAction.REJECT)), "mock review"),
            (
                MockReviewerProvider(
                    result=make_review(
                        AIReviewAction.APPROVE,
                        confidence=0.90,
                        critical=True,
                    )
                ),
                "critical_contradiction",
            ),
            (MockReviewerProvider(result=make_safe_reject_review()), "AI review parse failed"),
        ],
    )
    async def test_ai_reject_critical_or_invalid_json_never_reaches_execution(
        self,
        reviewer: MockReviewerProvider,
        reason: str,
    ) -> None:
        result, execution, storage = await _run_with_real_risk(
            _candidate(FinalAction.LONG, StrategyType.TREND_FOLLOWING),
            reviewer=reviewer,
        )

        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0
        assert reason in result.rejection_reason
        assert storage.get_decision_logs(result.run_id)[0]["final_action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_candidate_generation_exception_returns_hold_no_execution(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(decision=MockDecisionProvider(fail=True), execution=execution)
        result = await OrchestratorPipeline(
            deps,
            runner=AgentRunner(max_retries=0),
        ).run(_input())

        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0

    @pytest.mark.asyncio
    async def test_risk_engine_exception_returns_hold_no_execution(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(risk=type("RiskFail", (), {
            "call_count": 0,
            "validate_candidate": AsyncMock(side_effect=RuntimeError("risk down")),
        })(), execution=execution)
        result = await OrchestratorPipeline(
            deps,
            runner=AgentRunner(max_retries=0),
        ).run(_input())

        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0


class TestRiskGateDryRunBlocks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("candidate", "inp", "regime", "expected_code"),
        [
            (_candidate(stop_loss=None), None, MarketRegime.TREND_UP, "ORDER_003"),
            (_candidate(take_profit=None), None, MarketRegime.TREND_UP, "TAKE_PROFIT_MISSING"),
            (
                _candidate(strategy_type=StrategyType.INTRADAY, actual_rr=1.4),
                None,
                MarketRegime.TREND_UP,
                "STRATEGY_RR",
            ),
            (
                _candidate(expected_net_profit=Decimal("0.50")),
                None,
                MarketRegime.TREND_UP,
                "EXPECTED_PROFIT",
            ),
            (
                _candidate(liquidation_price=Decimal("94.95")),
                None,
                MarketRegime.TREND_UP,
                "LIQUIDATION_DISTANCE",
            ),
            (_candidate(spread_bps=6.0), None, MarketRegime.TREND_UP, "SPREAD_LIMIT"),
            (_candidate(slippage_bps=4.0), None, MarketRegime.TREND_UP, "SLIPPAGE_LIMIT"),
            (
                _candidate(strategy_type=StrategyType.SCALPING, actual_rr=1.1),
                None,
                MarketRegime.TREND_UP,
                "STRATEGY_RR",
            ),
            (
                _candidate(strategy_type=StrategyType.INTRADAY, actual_rr=1.4),
                None,
                MarketRegime.TREND_UP,
                "STRATEGY_RR",
            ),
            (
                _candidate(strategy_type=StrategyType.TREND_FOLLOWING, actual_rr=1.8),
                None,
                MarketRegime.TREND_UP,
                "STRATEGY_RR",
            ),
            (
                _candidate(),
                _input(daily_loss_usdt=Decimal("260")),
                MarketRegime.TREND_UP,
                "ORDER_001",
            ),
            (
                _candidate(),
                _input(weekly_loss_usdt=Decimal("1001")),
                MarketRegime.TREND_UP,
                "WEEKLY_LOSS",
            ),
            (
                _candidate(),
                _input(consecutive_losses=5),
                MarketRegime.TREND_UP,
                "CONSEC_LOSS",
            ),
            (_candidate(), None, MarketRegime.HIGH_VOLATILITY, "HIGH_VOLATILITY"),
            (_candidate(), None, MarketRegime.NEWS_EVENT, "NEWS_EVENT"),
        ],
    )
    async def test_risk_gate_blocks_every_required_failure_before_execution(
        self,
        candidate: TradeCandidate,
        inp: PipelineInput | None,
        regime: MarketRegime,
        expected_code: str,
    ) -> None:
        result, execution, storage = await _run_with_real_risk(
            candidate,
            inp=inp,
            regime=regime,
        )

        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0
        risk_step = result.step("risk")
        assert expected_code in risk_step.output.failed_checks
        log = storage.get_decision_logs(result.run_id)[0]
        assert expected_code in log["risk_failed_checks"]
        assert log["rejection_reason"]

    @pytest.mark.asyncio
    async def test_funding_time_blocked_before_execution(self) -> None:
        risk = _RealRiskProvider(RiskEngine(_redis()))
        execution = MockExecutionProvider()
        deps = make_deps(
            market_data=type("Market", (), {
                "get_snapshot": AsyncMock(return_value={
                    "coin": "BTC",
                    "current_price": 67000.0,
                    "ohlcv": {},
                    "funding_context": {"minutes_to_funding": 3},
                })
            })(),
            decision=MockDecisionProvider(
                result=_decision(_candidate(), MarketRegime.TREND_UP)
            ),
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=risk,
            execution=execution,
        )
        result = await OrchestratorPipeline(
            deps,
            runner=AgentRunner(max_retries=0),
        ).run(_input())

        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0
        assert "FUNDING_WINDOW" in result.step("risk").output.failed_checks


class TestCandidateAndStrategyDryRunInputs:
    def test_low_score_generates_hold_and_no_costly_candidate(self) -> None:
        candidate = _generated_candidate(chart=SignalScore(20, 10, 10, 0, []))

        assert candidate.action == FinalAction.HOLD

    def test_conflicting_long_short_scores_generate_hold(self) -> None:
        candidate = _generated_candidate(chart=SignalScore(82, 81, 10, 0, []))

        assert candidate.action == FinalAction.HOLD

    def test_fees_and_slippage_are_included_in_expected_net_profit(self) -> None:
        candidate = _generated_candidate(chart=SignalScore(80, 10, 10, 0, []))

        assert candidate.action == FinalAction.LONG
        assert candidate.expected_fees > 0
        assert candidate.expected_slippage_cost > 0
        assert candidate.expected_net_profit == (
            candidate.expected_gross_profit
            - candidate.expected_fees
            - candidate.expected_slippage_cost
        )

    def test_breakout_without_volume_confirmation_is_unknown(self) -> None:
        result = select_strategy_type(
            MarketRegime.RANGE,
            SignalScore(10, 10, 10, 0, []),
            _news(),
            _derivatives(),
            {"volume_ratio": 1.1, "price_change_pct": 0.5, "spread_bps": 1.0},
        )

        assert result.strategy_type == StrategyType.UNKNOWN

    def test_breakout_after_price_moved_too_far_is_unknown(self) -> None:
        result = select_strategy_type(
            MarketRegime.RANGE,
            SignalScore(20, 15, 10, 0, []),
            _news(),
            _derivatives(),
            {"volume_ratio": 2.2, "price_change_pct": 4.0, "spread_bps": 1.0},
            config={
                "min_intraday_dir_score": 90.0,
                "min_scalping_dir_score": 90.0,
            },
        )

        assert result.strategy_type == StrategyType.UNKNOWN


class TestShadowAndEmergencyDryRun:
    @pytest.mark.asyncio
    async def test_shadow_mode_never_places_real_orders_and_logs_decision(self) -> None:
        shadow = MockShadowExecutionProvider()
        result, execution, storage = await _run_with_real_risk(
            _candidate(FinalAction.LONG, StrategyType.TREND_FOLLOWING),
            execution=shadow,
        )

        assert result.status == PipelineStatus.COMPLETED
        assert execution.real_orders_placed == 0
        assert result.execution_result.placed_real_order is False
        assert storage.get_decision_logs(result.run_id)[0]["final_action"] == "LONG"

    @pytest.mark.asyncio
    async def test_tp_sl_registration_failure_triggers_emergency_close_path(self) -> None:
        exec_result = MockExecutionResult(
            tp_sl_failed=True,
            entry_order=MockOrder(),
            emergency_close_order=MockOrder(avg_fill_price=Decimal("99")),
        )
        result, execution, _ = await _run_with_real_risk(
            _candidate(FinalAction.LONG, StrategyType.TREND_FOLLOWING),
            execution=MockExecutionProvider(result=exec_result),
        )

        assert result.status == PipelineStatus.EMERGENCY_CLOSED
        assert execution.call_count == 1


def _news() -> NewsSentimentScore:
    return NewsSentimentScore(
        sentiment_score=0,
        long_score_adjustment=0,
        short_score_adjustment=0,
        risk_score=0,
        no_trade_flag=False,
        reasons=[],
    )


def _derivatives() -> DerivativesMarketScore:
    return DerivativesMarketScore(
        long_score_adjustment=0,
        short_score_adjustment=0,
        risk_score=0,
        crowded_side="NONE",
        reasons=[],
    )


def _generated_candidate(chart: SignalScore) -> TradeCandidate:
    return generate_trade_candidate(
        coin="BTC",
        symbol="BTCUSDT",
        market_snapshot={"current_price": 100.0, "spread_bps": 1.0},
        technical_result=type("TA", (), {
            "latest_close": 100.0,
            "analyses": {"1h": type("TF", (), {"close": 100.0, "atr": 2.0})()},
            "support_levels": [95.0],
            "resistance_levels": [110.0],
        })(),
        strategy_signal=type("Signal", (), {
            "entry_price": Decimal("100"),
            "stop_loss": Decimal("95"),
            "take_profit": Decimal("110"),
            "leverage": 5,
            "margin_ratio": 0.02,
        })(),
        market_regime=MarketRegime.TREND_UP,
        chart_score=chart,
        news_score=_news(),
        derivatives_score=_derivatives(),
        strategy_selection=StrategySelectionResult(
            strategy_type=StrategyType.INTRADAY,
            expected_holding_minutes=30,
            min_required_rr=1.5,
            reasons=[],
        ),
        account_state=type("Account", (), {"available_balance": Decimal("10000")})(),
        config={"max_risk_score": 80.0, "slippage_bps": 3.0},
    )
