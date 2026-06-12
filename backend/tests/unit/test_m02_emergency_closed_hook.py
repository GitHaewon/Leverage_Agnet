"""
M-02 단위 테스트 — EMERGENCY_CLOSED 경로에서 post_trade_hook 호출 보장

검증 항목:
  1.  EMERGENCY_CLOSED → post_trade_hook.on_trade_executed() 1회 호출
  2.  EMERGENCY_CLOSED + post_trade_hook=None → 예외 없이 EMERGENCY_CLOSED 반환
  3.  EMERGENCY_CLOSED + hook 예외 발생 → EMERGENCY_CLOSED 그대로 반환 (훅 실패 격리)
  4.  EMERGENCY_CLOSED → PostTradeEvent에 올바른 user_id / coin / direction / max_loss_usdt 전달
  5.  COMPLETED 경로 → hook 여전히 1회 호출됨 (회귀 방지)
  6.  FAILED (emergency_close_failed=True) → hook 호출 안 됨
  7.  EMERGENCY_CLOSED hook 호출 → SafetyGateAdapter.on_trade_closed() 체인 검증
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from agents.execution.models import ExecutionResult, FilledOrder
from agents.orchestrator.models import PipelineInput, PipelineStatus
from agents.risk.models import RawSignal, UserContext, AccountState, ValidationResult


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

def _filled(purpose: str = "entry", price: Decimal = Decimal("50000")) -> FilledOrder:
    return FilledOrder(
        exchange_order_id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        purpose=purpose,  # type: ignore[arg-type]
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        avg_fill_price=price,
        fee_usdt=Decimal("0.02"),
        filled_at=datetime.now(timezone.utc),
    )


_FIXED_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _pipeline_input(user_id: str = _FIXED_USER_ID) -> PipelineInput:
    user_ctx = MagicMock()
    user_ctx.user_id = user_id
    user_ctx.max_leverage = 20
    user_ctx.risk_per_trade_pct = Decimal("0.01")
    account = MagicMock()
    account.balance = Decimal("10000")
    return PipelineInput(
        coin="BTC",
        user_id=user_id,
        user_ctx=user_ctx,
        account_state=account,
        daily_loss_usdt=Decimal("100"),
        weekly_loss_usdt=Decimal("200"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions=[],
        portfolio_account=None,
    )


def _make_pipeline_deps(exec_result: ExecutionResult, hook=None):
    """
    최소 pipeline deps stub.
    ExecutionEngine은 exec_result를 즉시 반환하도록 고정.
    """
    from agents.orchestrator.pipeline import OrchestratorDeps

    market_data = AsyncMock()
    market_data.get_snapshot = AsyncMock(return_value={
        "ohlcv": {}, "current_price": 50000.0,
    })

    technical = MagicMock()
    technical.run = MagicMock(return_value=MagicMock(
        tech_score=0.6, timeframe_scores={}, indicators={},
        signals_fired=[], support_levels=[], resistance_levels=[],
    ))

    strategy = MagicMock()
    strategy.evaluate = MagicMock(return_value=MagicMock(
        sentiment_score=0.5, fear_greed_index=50, fear_greed_label="Neutral",
        dominant_sentiment="neutral", news_items=[], market_score=0.5,
        funding_rate=0.0, oi_1h_change_pct=0.0, long_short_ratio=1.0,
        long_account_pct=50.0, whale_activity="neutral",
    ))

    decision, reviewer = _decision_and_reviewer()

    validation_mock = MagicMock()
    validation_mock.approved          = True
    validation_mock.rejection_code    = None
    validation_mock.rejection_reason  = None
    validation_mock.warnings          = []
    validation_mock.quantity          = Decimal("0.001")
    validation_mock.final_leverage    = 5
    validation_mock.max_loss_usdt     = Decimal("200")

    risk = AsyncMock()
    risk.validate_candidate = AsyncMock(return_value=validation_mock)

    portfolio = MagicMock()
    portfolio.can_add_position = MagicMock(return_value=(True, "OK"))

    position_manager = MagicMock()
    position_manager.open = MagicMock(return_value=MagicMock())

    execution = AsyncMock()
    execution.execute = AsyncMock(return_value=exec_result)

    return OrchestratorDeps(
        market_data=market_data,
        technical=technical,
        strategy=strategy,
        decision=decision,
        reviewer=reviewer,
        risk=risk,
        portfolio=portfolio,
        position_manager=position_manager,
        execution=execution,
        post_trade_hook=hook,
    )


def _decision_and_reviewer(direction: str = "LONG"):
    """결정적 LONG/SHORT 후보 + AI APPROVE 리뷰어 mock (새 의사결정 플로우)."""
    from agents.decision.engine import DecisionResult
    from agents.decision.models import (
        AIReviewAction, AIReviewResult, FinalAction, StrategyType, TradeCandidate,
    )

    is_long = direction == "LONG"
    action = FinalAction.LONG if is_long else FinalAction.SHORT
    candidate = TradeCandidate(
        action=action, coin="BTC", symbol="BTCUSDT",
        strategy_type=StrategyType.TREND_FOLLOWING, expected_holding_minutes=120,
        entry_price=Decimal("50000"),
        stop_loss=Decimal("48000") if is_long else Decimal("52000"),
        take_profit=Decimal("55000") if is_long else Decimal("45000"),
        leverage=5, margin_ratio=0.015, notional_size=Decimal("5000"),
        actual_rr=2.5, min_required_rr=2.0,
        expected_gross_profit=Decimal("250"), expected_gross_loss=Decimal("100"),
        expected_fees=Decimal("5"), expected_slippage_cost=Decimal("3"),
        expected_net_profit=Decimal("200"), expected_net_loss=Decimal("108"),
        liquidation_price=Decimal("40000") if is_long else Decimal("60000"),
        spread_bps=1.0, slippage_bps=3.0, reasons=[direction],
    )
    decision = MagicMock()
    decision.run = MagicMock(return_value=DecisionResult(
        regime=None, chart_score=None, news_score=None, derivatives_score=None,
        strategy_selection=None, candidate=candidate, confidence=0.8,
    ))
    reviewer = AsyncMock()
    reviewer.review = AsyncMock(return_value=AIReviewResult(
        review_action=AIReviewAction.APPROVE, confidence=0.85,
        critical_contradiction=False, risk_warnings=[], reason_summary="ok",
    ))
    return decision, reviewer


def _emergency_closed_er() -> ExecutionResult:
    """tp_sl_failed=True, 긴급 청산 성공 ExecutionResult."""
    return ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_sl_failed=True,
        emergency_close_order=_filled("emergency_close"),
        emergency_close_failed=False,
    )


def _completed_er() -> ExecutionResult:
    """정상 완료 ExecutionResult."""
    return ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_order=_filled("take_profit"),
        sl_order=_filled("stop_loss"),
        tp_sl_failed=False,
    )


def _hook() -> AsyncMock:
    h = AsyncMock()
    h.on_trade_executed = AsyncMock()
    return h


# ── Group 1: EMERGENCY_CLOSED → hook 호출 ────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_closed_calls_hook():
    """tp_sl_failed=True → post_trade_hook.on_trade_executed() 1회 호출."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    hook = _hook()
    deps = _make_pipeline_deps(_emergency_closed_er(), hook=hook)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    hook.on_trade_executed.assert_awaited_once()


@pytest.mark.asyncio
async def test_emergency_closed_without_hook_no_error():
    """post_trade_hook=None 일 때 EMERGENCY_CLOSED 경로 — 예외 없이 정상 반환."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    deps = _make_pipeline_deps(_emergency_closed_er(), hook=None)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED


@pytest.mark.asyncio
async def test_emergency_closed_hook_exception_does_not_change_status():
    """hook에서 예외 발생 시 파이프라인 결과는 EMERGENCY_CLOSED 그대로."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    hook = _hook()
    hook.on_trade_executed = AsyncMock(side_effect=RuntimeError("hook exploded"))

    deps   = _make_pipeline_deps(_emergency_closed_er(), hook=hook)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    hook.on_trade_executed.assert_awaited_once()


# ── Group 2: PostTradeEvent 내용 검증 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_closed_hook_event_fields():
    """hook에 전달된 PostTradeEvent — user_id, coin, direction, max_loss_usdt 검증."""
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from agents.orchestrator.models import PostTradeEvent

    received: list[PostTradeEvent] = []

    async def capture(event: PostTradeEvent) -> None:
        received.append(event)

    hook = MagicMock()
    hook.on_trade_executed = capture

    user_id = str(uuid.uuid4())
    deps    = _make_pipeline_deps(_emergency_closed_er(), hook=hook)
    inp     = _pipeline_input(user_id=user_id)

    await OrchestratorPipeline(deps).run(inp)

    assert len(received) == 1
    ev = received[0]
    assert ev.user_id    == user_id
    assert ev.coin       == "BTC"
    assert ev.direction  == "LONG"        # analyst_result.decision.decision = "LONG"
    assert ev.max_loss_usdt == pytest.approx(200.0)  # validation_mock.max_loss_usdt = 200


@pytest.mark.asyncio
async def test_emergency_closed_hook_event_balances():
    """PostTradeEvent 잔고 필드 — period_start_balance = balance + daily_loss."""
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from agents.orchestrator.models import PostTradeEvent

    received: list[PostTradeEvent] = []

    async def capture(event: PostTradeEvent) -> None:
        received.append(event)

    hook = MagicMock()
    hook.on_trade_executed = capture

    # PipelineInput: balance=10000, daily_loss=100, weekly_loss=200
    deps = _make_pipeline_deps(_emergency_closed_er(), hook=hook)
    await OrchestratorPipeline(deps).run(_pipeline_input())

    ev = received[0]
    assert ev.current_balance        == pytest.approx(10000.0)
    assert ev.period_start_balance   == pytest.approx(10100.0)  # 10000 + 100
    assert ev.week_start_balance     == pytest.approx(10200.0)  # 10000 + 200


# ── Group 3: 회귀 방지 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_completed_path_does_not_call_hook():
    """COMPLETED 경로(TP/SL 걸린 포지션 미청산) — hook 호출 안 됨. (M-03 fix)

    포지션이 아직 열려 있으므로 미실현 P&L로 kill switch를 누적하지 않는다.
    실제 청산 시 모니터링 워커가 on_trade_closed()를 호출한다.
    """
    from agents.orchestrator.pipeline import OrchestratorPipeline

    hook = _hook()
    deps = _make_pipeline_deps(_completed_er(), hook=hook)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.COMPLETED
    hook.on_trade_executed.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_emergency_close_failed_does_not_call_hook():
    """emergency_close_failed=True (FAILED 경로) → hook 호출 안 됨."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_sl_failed=True,
        emergency_close_failed=True,
    )
    hook = _hook()
    deps = _make_pipeline_deps(er, hook=hook)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.FAILED
    hook.on_trade_executed.assert_not_awaited()


# ── Group 4: SafetyGateAdapter 체인 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_closed_triggers_safety_gate_adapter():
    """
    EMERGENCY_CLOSED → SafetyGateAdapter.on_trade_executed() 호출
    → gate.on_trade_closed()에 실제 fill P&L 전달 검증 (M-03 fix).
    entry=$50000, emergency_close=$49800 → realized_pnl = (49800-50000)*0.001 = -0.2 USDT
    """
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[])

    adapter = SafetyGateAdapter(gate=mock_gate)

    # 손실 시나리오: entry $50000, emergency close $49800
    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry",          Decimal("50000")),
        tp_sl_failed=True,
        emergency_close_order=_filled("emergency_close", Decimal("49800")),
        emergency_close_failed=False,
    )
    deps = _make_pipeline_deps(er, hook=adapter)

    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    mock_gate.on_trade_closed.assert_awaited_once()

    call_kwargs = mock_gate.on_trade_closed.call_args
    assert call_kwargs.kwargs["user_id"] == _FIXED_USER_ID
    # realized_pnl_usdt = (49800 - 50000) * 0.001 = -0.2, NOT -max_loss_usdt(-200)
    assert call_kwargs.kwargs["pnl_usdt"] == pytest.approx(-0.2)
