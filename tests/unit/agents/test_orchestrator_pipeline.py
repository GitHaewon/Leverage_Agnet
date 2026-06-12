"""
OrchestratorPipeline 통합 테스트 (결정적 의사결정 플로우).

플로우: market_data → technical → strategy → decision → ai_review
        → risk → final_decision → portfolio → position_manager → execution

핵심 안전 검증:
  1. 결정적 LONG 후보 + AI 승인 + 리스크 통과 → 실행 경로 도달
  2. 결정적 SHORT 후보 + AI 승인 + 리스크 통과 → 실행 경로 도달
  3. AI 승인이나 리스크 실패 → HOLD, 실행 없음
  4. AI 거부 → HOLD, 실행 없음
  5. FinalDecision HOLD → 실행 없음
  6. 후보 생성 오류 → HOLD, 실행 없음
  7. AI 리뷰 파싱 실패 → HOLD, 실행 없음
  8. RiskEngine 예외 → HOLD, 실행 없음
  9. Shadow 모드는 실제 주문을 넣지 않는다
 10. 긴급 TP/SL 실패 처리 유지
"""
from __future__ import annotations

import pytest

from agents.decision.models import AIReviewAction, FinalAction, StrategyType
from agents.orchestrator.models import AgentStatus, PipelineStatus
from agents.orchestrator.pipeline import OrchestratorPipeline
from agents.orchestrator.runner import AgentRunner

from tests.unit.agents._orchestrator_fixtures import (
    MockDecisionProvider,
    MockExecutionProvider,
    MockMarketDataProvider,
    MockPortfolioProvider,
    MockPositionManagerProvider,
    MockReviewerProvider,
    MockRiskProvider,
    MockShadowExecutionProvider,
    MockStrategyProvider,
    MockTechnicalProvider,
    MockExecutionResult,
    MockOrder,
    MockValidationResult,
    make_candidate,
    make_decision_result,
    make_deps,
    make_input,
    make_review,
    make_safe_reject_review,
)


def _pipeline(deps) -> OrchestratorPipeline:
    return OrchestratorPipeline(deps, runner=AgentRunner(max_retries=0))


# ── 1 & 2. 정상 실행 경로 (LONG / SHORT) ──────────────────────────────────────

class TestExecutionPathAllowed:
    @pytest.mark.asyncio
    async def test_long_candidate_approve_risk_pass_reaches_execution(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            decision=MockDecisionProvider(
                result=make_decision_result(make_candidate(FinalAction.LONG))
            ),
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input("BTC"))

        assert result.status == PipelineStatus.COMPLETED
        assert execution.call_count == 1

    @pytest.mark.asyncio
    async def test_short_candidate_approve_risk_pass_reaches_execution(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            decision=MockDecisionProvider(
                result=make_decision_result(make_candidate(FinalAction.SHORT))
            ),
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input("ETH"))

        assert result.status == PipelineStatus.COMPLETED
        assert execution.call_count == 1

    @pytest.mark.asyncio
    async def test_raw_signal_direction_comes_from_candidate(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            decision=MockDecisionProvider(
                result=make_decision_result(make_candidate(FinalAction.SHORT))
            ),
            execution=execution,
        )
        await _pipeline(deps).run(make_input())
        # RawSignal은 candidate에서 생성 — AI가 아니라 결정적 후보가 방향을 결정
        assert execution.last_request.signal.direction == "SHORT"

    @pytest.mark.asyncio
    async def test_completed_has_ten_steps(self) -> None:
        result = await _pipeline(make_deps()).run(make_input())
        assert len(result.steps) == 10

    @pytest.mark.asyncio
    async def test_all_steps_success_on_happy_path(self) -> None:
        result = await _pipeline(make_deps()).run(make_input())
        for step in result.steps:
            assert step.status == AgentStatus.SUCCESS, f"{step.agent_name}: {step.status}"


# ── 3. AI 승인 + 리스크 실패 → HOLD, 실행 없음 ────────────────────────────────

class TestRiskFailNoExecution:
    @pytest.mark.asyncio
    async def test_risk_rejected_returns_hold_no_execution(self) -> None:
        execution = MockExecutionProvider()
        pm = MockPositionManagerProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(
                result=MockValidationResult(
                    approved=False, rejection_reason="일일 손실 한도 도달",
                    failed_checks=["ORDER_001"],
                )
            ),
            position_manager=pm,
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input())

        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0
        assert pm.call_count == 0

    @pytest.mark.asyncio
    async def test_risk_rejected_reason_propagated(self) -> None:
        deps = make_deps(
            risk=MockRiskProvider(
                result=MockValidationResult(approved=False, rejection_reason="한도 초과")
            ),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.rejection_reason == "한도 초과"

    @pytest.mark.asyncio
    async def test_risk_fail_skips_final_decision(self) -> None:
        deps = make_deps(
            risk=MockRiskProvider(result=MockValidationResult(approved=False)),
        )
        result = await _pipeline(deps).run(make_input())
        skipped = {s.agent_name for s in result.skipped_steps}
        assert "final_decision" in skipped
        assert "portfolio" in skipped


# ── 4. AI 거부 → HOLD, 실행 없음 ──────────────────────────────────────────────

class TestAIRejectNoExecution:
    @pytest.mark.asyncio
    async def test_ai_reject_returns_hold(self) -> None:
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.REJECT)),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD

    @pytest.mark.asyncio
    async def test_ai_reject_skips_risk_and_execution(self) -> None:
        risk = MockRiskProvider()
        execution = MockExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.REJECT)),
            risk=risk,
            execution=execution,
        )
        await _pipeline(deps).run(make_input())
        # AI 거부만으로 실행에 도달하지 않으며, 이후 RiskEngine도 호출되지 않는다
        assert risk.call_count == 0
        assert execution.call_count == 0

    @pytest.mark.asyncio
    async def test_ai_approve_alone_does_not_execute_without_risk(self) -> None:
        # AI 승인이지만 리스크 거부 → 실행 없음 (승인만으로 실행 금지)
        execution = MockExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=False)),
            execution=execution,
        )
        await _pipeline(deps).run(make_input())
        assert execution.call_count == 0


# ── 5. FinalDecision HOLD → 실행 없음 ─────────────────────────────────────────

class TestFinalDecisionHold:
    @pytest.mark.asyncio
    async def test_low_ai_confidence_final_hold_no_execution(self) -> None:
        # AI APPROVE but confidence < MIN_AI_REVIEW_CONFIDENCE(0.70) → FinalDecision HOLD
        execution = MockExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(
                result=make_review(AIReviewAction.APPROVE, confidence=0.50)
            ),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0

    @pytest.mark.asyncio
    async def test_final_decision_hold_skips_portfolio_pm_execution(self) -> None:
        deps = make_deps(
            reviewer=MockReviewerProvider(
                result=make_review(AIReviewAction.APPROVE, confidence=0.50)
            ),
        )
        result = await _pipeline(deps).run(make_input())
        skipped = {s.agent_name for s in result.skipped_steps}
        assert {"portfolio", "position_manager", "execution"} <= skipped

    @pytest.mark.asyncio
    async def test_critical_contradiction_final_hold(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(
                result=make_review(AIReviewAction.APPROVE, confidence=0.9, critical=True)
            ),
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0


# ── 6. 후보 생성 오류 → HOLD, 실행 없음 ───────────────────────────────────────

class TestDecisionError:
    @pytest.mark.asyncio
    async def test_decision_exception_returns_hold(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(decision=MockDecisionProvider(fail=True), execution=execution)
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0

    @pytest.mark.asyncio
    async def test_decision_exception_skips_ai_review(self) -> None:
        reviewer = MockReviewerProvider()
        deps = make_deps(decision=MockDecisionProvider(fail=True), reviewer=reviewer)
        result = await _pipeline(deps).run(make_input())
        assert reviewer.call_count == 0
        skipped = {s.agent_name for s in result.skipped_steps}
        assert "ai_review" in skipped

    @pytest.mark.asyncio
    async def test_candidate_hold_returns_hold(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            decision=MockDecisionProvider(
                result=make_decision_result(make_candidate(FinalAction.HOLD))
            ),
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0

    @pytest.mark.asyncio
    async def test_unknown_strategy_candidate_hold(self) -> None:
        # UNKNOWN 전략 후보는 generate가 HOLD로 만들지만, 방어적으로도 HOLD 보장
        candidate = make_candidate(FinalAction.HOLD, StrategyType.UNKNOWN)
        deps = make_deps(
            decision=MockDecisionProvider(result=make_decision_result(candidate)),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD


# ── 7. AI 리뷰 파싱 실패 → HOLD, 실행 없음 ───────────────────────────────────

class TestAIReviewParseFailure:
    @pytest.mark.asyncio
    async def test_safe_reject_review_returns_hold(self) -> None:
        # ReviewerAgent는 파싱 실패를 안전 REJECT로 변환 → 파이프라인 HOLD
        execution = MockExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_safe_reject_review()),
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0

    @pytest.mark.asyncio
    async def test_reviewer_exception_returns_hold(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(fail=True),
            execution=execution,
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0


# ── 8. RiskEngine 예외 → HOLD, 실행 없음 ─────────────────────────────────────

class TestRiskException:
    @pytest.mark.asyncio
    async def test_risk_exception_returns_hold(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(risk=MockRiskProvider(fail=True), execution=execution)
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.HOLD
        assert execution.call_count == 0

    @pytest.mark.asyncio
    async def test_risk_exception_skips_downstream(self) -> None:
        deps = make_deps(risk=MockRiskProvider(fail=True))
        result = await _pipeline(deps).run(make_input())
        skipped = {s.agent_name for s in result.skipped_steps}
        assert {"final_decision", "portfolio", "position_manager", "execution"} <= skipped


# ── 9. Shadow 모드는 실제 주문 없음 ──────────────────────────────────────────

class TestShadowMode:
    @pytest.mark.asyncio
    async def test_shadow_execution_places_no_real_order(self) -> None:
        shadow = MockShadowExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=shadow,
        )
        result = await _pipeline(deps).run(make_input())

        assert result.status == PipelineStatus.COMPLETED
        assert shadow.call_count == 1
        assert shadow.real_orders_placed == 0
        assert result.execution_result.placed_real_order is False
        assert result.execution_result.mode == "shadow"

    @pytest.mark.asyncio
    async def test_shadow_hold_does_not_call_execution(self) -> None:
        shadow = MockShadowExecutionProvider()
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.REJECT)),
            execution=shadow,
        )
        await _pipeline(deps).run(make_input())
        assert shadow.call_count == 0


# ── 10. 긴급 TP/SL 실패 처리 ──────────────────────────────────────────────────

class TestEmergencyTpSl:
    @pytest.mark.asyncio
    async def test_tp_sl_failure_emergency_closed_status(self) -> None:
        exec_result = MockExecutionResult(
            tp_sl_failed=True,
            entry_order=MockOrder(),
            emergency_close_order=MockOrder(avg_fill_price="66950"),
        )
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=MockExecutionProvider(result=exec_result),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.EMERGENCY_CLOSED

    @pytest.mark.asyncio
    async def test_emergency_close_failure_returns_failed(self) -> None:
        exec_result = MockExecutionResult(
            tp_sl_failed=True,
            emergency_close_failed=True,
            entry_order=MockOrder(),
        )
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=MockExecutionProvider(result=exec_result),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_post_trade_hook_fired_on_emergency_close(self) -> None:
        fired: list = []

        class _Hook:
            async def on_trade_executed(self, event) -> None:
                fired.append(event)

        exec_result = MockExecutionResult(
            tp_sl_failed=True,
            entry_order=MockOrder(),
            emergency_close_order=MockOrder(avg_fill_price="66950"),
        )
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=MockExecutionProvider(result=exec_result),
        )
        deps.post_trade_hook = _Hook()
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.EMERGENCY_CLOSED
        assert len(fired) == 1


# ── 인프라 실패 (CRITICAL) ────────────────────────────────────────────────────

class TestCriticalFailures:
    @pytest.mark.asyncio
    async def test_market_data_failure_returns_failed(self) -> None:
        deps = make_deps(market_data=MockMarketDataProvider(fail=True))
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_market_data_failure_skips_all_downstream(self) -> None:
        execution = MockExecutionProvider()
        deps = make_deps(
            market_data=MockMarketDataProvider(fail=True), execution=execution
        )
        result = await _pipeline(deps).run(make_input())
        assert execution.call_count == 0
        assert len(result.skipped_steps) == 9

    @pytest.mark.asyncio
    async def test_position_manager_failure_returns_failed(self) -> None:
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            position_manager=MockPositionManagerProvider(fail=True),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_execution_failure_returns_failed(self) -> None:
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            execution=MockExecutionProvider(fail=True),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.FAILED


# ── DEGRADED 실패 (중립값 사용 후 계속) ────────────────────────────────────────

class TestDegradedFlow:
    @pytest.mark.asyncio
    async def test_technical_failure_pipeline_continues(self) -> None:
        deps = make_deps(technical=MockTechnicalProvider(fail=True))
        result = await _pipeline(deps).run(make_input())
        assert result.status != PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_strategy_failure_pipeline_continues(self) -> None:
        deps = make_deps(strategy=MockStrategyProvider(fail=True))
        result = await _pipeline(deps).run(make_input())
        assert result.status != PipelineStatus.FAILED


# ── Portfolio 거부 ────────────────────────────────────────────────────────────

class TestPortfolioRejection:
    @pytest.mark.asyncio
    async def test_portfolio_rejected_returns_rejected(self) -> None:
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            portfolio=MockPortfolioProvider(can_add=False, reason="포트폴리오 한도 초과"),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.REJECTED
        assert "포트폴리오" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_portfolio_exception_returns_rejected(self) -> None:
        deps = make_deps(
            reviewer=MockReviewerProvider(result=make_review(AIReviewAction.APPROVE)),
            risk=MockRiskProvider(result=MockValidationResult(approved=True)),
            portfolio=MockPortfolioProvider(fail=True),
        )
        result = await _pipeline(deps).run(make_input())
        assert result.status == PipelineStatus.REJECTED


# ── 스텝 구조 검증 ─────────────────────────────────────────────────────────────

class TestStepStructure:
    _STEP_NAMES = [
        "market_data", "technical", "strategy", "decision", "ai_review",
        "risk", "final_decision", "portfolio", "position_manager", "execution",
    ]

    @pytest.mark.asyncio
    async def test_step_names_in_order(self) -> None:
        result = await _pipeline(make_deps()).run(make_input())
        assert [s.agent_name for s in result.steps] == self._STEP_NAMES

    @pytest.mark.asyncio
    async def test_run_id_unique(self) -> None:
        p = _pipeline(make_deps())
        r1 = await p.run(make_input())
        r2 = await p.run(make_input())
        assert r1.run_id != r2.run_id

    @pytest.mark.asyncio
    async def test_each_agent_called_once_on_happy_path(self) -> None:
        market = MockMarketDataProvider()
        decision = MockDecisionProvider()
        reviewer = MockReviewerProvider()
        risk = MockRiskProvider()
        execution = MockExecutionProvider()
        deps = make_deps(
            market_data=market, decision=decision, reviewer=reviewer,
            risk=risk, execution=execution,
        )
        await _pipeline(deps).run(make_input())
        assert market.call_count == 1
        assert decision.call_count == 1
        assert reviewer.call_count == 1
        assert risk.call_count == 1
        assert execution.call_count == 1
