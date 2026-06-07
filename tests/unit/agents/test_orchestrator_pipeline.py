"""
OrchestratorPipeline 통합 테스트.

검증 항목:
  - 정상 플로우: 8단계 전부 성공 → COMPLETED
  - HOLD 판정: AIAnalyst HOLD → 이후 4개 step SKIPPED
  - Risk 거부: RiskEngine approved=False → REJECTED + 이후 skip
  - Portfolio 거부: PortfolioEngine → REJECTED + 이후 skip
  - MarketData 실패 → FAILED + 이후 7개 step SKIPPED
  - Technical 실패 → 중립값 사용, 파이프라인 계속
  - Strategy 실패 → 중립값 사용, 파이프라인 계속
  - AIAnalyst 실패 → FAILED
  - RiskEngine 예외 → REJECTED (보수적)
  - PortfolioEngine 예외 → REJECTED (보수적)
  - PositionManager 실패 → FAILED
  - ExecutionEngine 실패 → FAILED
  - 스텝 수 정확히 8개 (성공/실패/skip 합산)
  - 각 에이전트 호출 횟수 검증
  - PipelineResult.run_id 고유성
"""
from __future__ import annotations

import pytest

from agents.orchestrator.models import PipelineStatus, AgentStatus
from agents.orchestrator.pipeline import OrchestratorPipeline
from agents.orchestrator.runner import AgentRunner

from tests.unit.agents._orchestrator_fixtures import (
    MockAnalystProvider,
    MockHoldAnalystResult,
    MockMarketDataProvider,
    MockPortfolioProvider,
    MockPositionManagerProvider,
    MockRiskProvider,
    MockStrategyProvider,
    MockTechnicalProvider,
    MockExecutionProvider,
    MockValidationResult,
    make_deps,
    make_input,
)


# ── 정상 플로우 ───────────────────────────────────────────────────────────────

class TestNormalFlow:
    @pytest.mark.asyncio
    async def test_all_steps_succeed_returns_completed(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input("BTC"))

        assert result.status == PipelineStatus.COMPLETED
        assert result.succeeded is True
        assert result.execution_result is not None

    @pytest.mark.asyncio
    async def test_result_has_exactly_eight_steps(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert len(result.steps) == 8

    @pytest.mark.asyncio
    async def test_all_steps_succeed_status(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        for step in result.steps:
            assert step.status == AgentStatus.SUCCESS, f"{step.agent_name}: {step.status}"

    @pytest.mark.asyncio
    async def test_run_id_is_unique(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        r1 = await pipeline.run(make_input())
        r2 = await pipeline.run(make_input())
        assert r1.run_id != r2.run_id

    @pytest.mark.asyncio
    async def test_coin_propagated_to_result(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input("ETH"))
        assert result.coin == "ETH"

    @pytest.mark.asyncio
    async def test_total_latency_positive(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.total_latency_ms > 0

    @pytest.mark.asyncio
    async def test_each_agent_called_once(self) -> None:
        market = MockMarketDataProvider()
        tech = MockTechnicalProvider()
        strategy = MockStrategyProvider()
        analyst = MockAnalystProvider()
        risk = MockRiskProvider()
        portfolio = MockPortfolioProvider()
        pm = MockPositionManagerProvider()
        execution = MockExecutionProvider()
        deps = make_deps(
            market_data=market, technical=tech, strategy=strategy,
            analyst=analyst, risk=risk, portfolio=portfolio,
            position_manager=pm, execution=execution,
        )
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        await pipeline.run(make_input())

        assert market.call_count == 1
        assert tech.call_count == 1
        assert strategy.call_count == 1
        assert analyst.call_count == 1
        assert risk.call_count == 1
        assert portfolio.call_count == 1
        assert pm.call_count == 1
        assert execution.call_count == 1


# ── HOLD 판정 ─────────────────────────────────────────────────────────────────

class TestHoldFlow:
    @pytest.mark.asyncio
    async def test_hold_returns_hold_status(self) -> None:
        deps = make_deps(analyst=MockAnalystProvider(result=MockHoldAnalystResult()))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.HOLD

    @pytest.mark.asyncio
    async def test_hold_skips_downstream_steps(self) -> None:
        deps = make_deps(analyst=MockAnalystProvider(result=MockHoldAnalystResult()))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())

        skipped = {s.agent_name for s in result.skipped_steps}
        assert "risk" in skipped
        assert "portfolio" in skipped
        assert "position_manager" in skipped
        assert "execution" in skipped

    @pytest.mark.asyncio
    async def test_hold_does_not_call_risk(self) -> None:
        risk = MockRiskProvider()
        deps = make_deps(
            analyst=MockAnalystProvider(result=MockHoldAnalystResult()),
            risk=risk,
        )
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        await pipeline.run(make_input())
        assert risk.call_count == 0

    @pytest.mark.asyncio
    async def test_hold_total_steps_still_eight(self) -> None:
        deps = make_deps(analyst=MockAnalystProvider(result=MockHoldAnalystResult()))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert len(result.steps) == 8


# ── Risk 거부 ─────────────────────────────────────────────────────────────────

class TestRiskRejection:
    @pytest.mark.asyncio
    async def test_risk_rejected_returns_rejected_status(self) -> None:
        rejected = MockValidationResult(
            approved=False,
            rejection_code="ORDER_001",
            rejection_reason="일일 손실 한도 도달",
        )
        deps = make_deps(risk=MockRiskProvider(result=rejected))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.REJECTED

    @pytest.mark.asyncio
    async def test_risk_rejected_reason_propagated(self) -> None:
        rejected = MockValidationResult(
            approved=False,
            rejection_reason="일일 손실 한도 도달",
        )
        deps = make_deps(risk=MockRiskProvider(result=rejected))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.rejection_reason == "일일 손실 한도 도달"

    @pytest.mark.asyncio
    async def test_risk_rejected_skips_downstream(self) -> None:
        rejected = MockValidationResult(approved=False, rejection_reason="한도 초과")
        pm = MockPositionManagerProvider()
        execution = MockExecutionProvider()
        deps = make_deps(
            risk=MockRiskProvider(result=rejected),
            position_manager=pm,
            execution=execution,
        )
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        await pipeline.run(make_input())
        assert pm.call_count == 0
        assert execution.call_count == 0


# ── Portfolio 거부 ────────────────────────────────────────────────────────────

class TestPortfolioRejection:
    @pytest.mark.asyncio
    async def test_portfolio_rejected_returns_rejected(self) -> None:
        deps = make_deps(
            portfolio=MockPortfolioProvider(can_add=False, reason="포트폴리오 한도 초과")
        )
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.REJECTED
        assert "포트폴리오" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_portfolio_rejected_skips_execution(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            portfolio=MockPortfolioProvider(can_add=False, reason="한도 초과"),
            execution=execution,
        )
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        await pipeline.run(make_input())
        assert execution.call_count == 0


# ── 크리티컬 실패 ─────────────────────────────────────────────────────────────

class TestCriticalFailures:
    @pytest.mark.asyncio
    async def test_market_data_failure_returns_failed(self) -> None:
        deps = make_deps(market_data=MockMarketDataProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_market_data_failure_skips_all_downstream(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            market_data=MockMarketDataProvider(fail=True),
            execution=execution,
        )
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert execution.call_count == 0
        assert len(result.skipped_steps) == 7

    @pytest.mark.asyncio
    async def test_analyst_failure_returns_failed(self) -> None:
        deps = make_deps(analyst=MockAnalystProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_execution_failure_returns_failed(self) -> None:
        deps = make_deps(execution=MockExecutionProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.FAILED


# ── DEGRADED 실패 (중립값 사용 후 계속) ────────────────────────────────────────

class TestDegradedFlow:
    @pytest.mark.asyncio
    async def test_technical_failure_pipeline_continues(self) -> None:
        deps = make_deps(technical=MockTechnicalProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        # 계속 진행되어 COMPLETED or HOLD 또는 REJECTED (실패 아님)
        assert result.status != PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_technical_failure_step_is_failed_in_steps(self) -> None:
        deps = make_deps(technical=MockTechnicalProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        tech_step = result.step("technical")
        assert tech_step is not None
        assert tech_step.status == AgentStatus.FAILED

    @pytest.mark.asyncio
    async def test_strategy_failure_pipeline_continues(self) -> None:
        deps = make_deps(strategy=MockStrategyProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status != PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_both_ta_and_strategy_fail_pipeline_continues(self) -> None:
        deps = make_deps(
            technical=MockTechnicalProvider(fail=True),
            strategy=MockStrategyProvider(fail=True),
        )
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status != PipelineStatus.FAILED


# ── 보수적 거부 (Risk/Portfolio 예외) ─────────────────────────────────────────

class TestConservativeRejection:
    @pytest.mark.asyncio
    async def test_risk_exception_causes_rejected(self) -> None:
        deps = make_deps(risk=MockRiskProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.REJECTED

    @pytest.mark.asyncio
    async def test_portfolio_exception_causes_rejected(self) -> None:
        deps = make_deps(portfolio=MockPortfolioProvider(fail=True))
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert result.status == PipelineStatus.REJECTED


# ── 스텝 구조 검증 ─────────────────────────────────────────────────────────────

class TestStepStructure:
    _STEP_NAMES = [
        "market_data", "technical", "strategy", "ai_analyst",
        "risk", "portfolio", "position_manager", "execution",
    ]

    @pytest.mark.asyncio
    async def test_step_names_in_order(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert [s.agent_name for s in result.steps] == self._STEP_NAMES

    @pytest.mark.asyncio
    async def test_step_lookup_after_pipeline(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        for name in self._STEP_NAMES:
            assert result.step(name) is not None

    @pytest.mark.asyncio
    async def test_no_extra_steps(self) -> None:
        deps = make_deps()
        pipeline = OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))
        result = await pipeline.run(make_input())
        assert len(result.steps) == 8
