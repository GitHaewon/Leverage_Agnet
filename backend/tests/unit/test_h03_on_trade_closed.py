"""
H-03 단위 테스트 — SafetyGate.on_trade_closed() 호출 보장.

검증 항목:
  1. SafetyGateAdapter.on_trade_executed()  → gate.on_trade_closed() 위임
  2. max_loss_usdt=200  → pnl_usdt=-200 전달
  3. period/week 잔고 계산이 올바르게 전달됨
  4. SafetyGateAdapter는 PostTradeHookProvider 프로토콜을 만족함
  5. Daily kill switch — on_trade_executed 반복 → 임계값 초과 시 트리거
  6. Weekly kill switch — on_trade_executed 반복 → 임계값 초과 시 트리거
  7. Pipeline executed=True  → post_trade_hook.on_trade_executed 호출됨
  8. Pipeline executed=False → hook 호출 안 됨
  9. hook 예외 → pipeline 결과에 영향 없음 (COMPLETED 유지)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.orchestrator.models import PostTradeEvent
from agents.orchestrator.pipeline import (
    OrchestratorDeps,
    OrchestratorPipeline,
    PostTradeHookProvider,
)
from agents.orchestrator.models import PipelineStatus


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

def _make_event(
    user_id: str = "user-001",
    max_loss_usdt: float = 200.0,
    period_start: float = 10000.0,
    week_start: float = 10000.0,
    current: float = 9800.0,
) -> PostTradeEvent:
    return PostTradeEvent(
        user_id=user_id,
        coin="BTC",
        direction="LONG",
        entry_price=Decimal("50000"),
        quantity=Decimal("0.004"),
        stop_loss=Decimal("45000"),
        max_loss_usdt=max_loss_usdt,
        period_start_balance=period_start,
        week_start_balance=week_start,
        current_balance=current,
    )


# ── Group 1: SafetyGateAdapter.on_trade_executed ─────────────────────────────

@pytest.mark.asyncio
async def test_adapter_delegates_to_gate_on_trade_closed():
    """on_trade_executed → gate.on_trade_closed 단순 위임."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[])
    adapter = SafetyGateAdapter(mock_gate)

    await adapter.on_trade_executed(_make_event(max_loss_usdt=200.0))

    mock_gate.on_trade_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_adapter_passes_negative_max_loss_as_pnl():
    """max_loss_usdt=200 → pnl_usdt=-200 전달 (손실 누적)."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[])
    adapter = SafetyGateAdapter(mock_gate)

    await adapter.on_trade_executed(_make_event(max_loss_usdt=200.0))

    call_kwargs = mock_gate.on_trade_closed.call_args
    assert call_kwargs.kwargs["pnl_usdt"] == -200.0


@pytest.mark.asyncio
async def test_adapter_passes_correct_balance_fields():
    """period/week/current balance가 올바르게 전달된다."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[])
    adapter = SafetyGateAdapter(mock_gate)

    event = _make_event(
        period_start=9500.0,
        week_start=9800.0,
        current=9300.0,
    )
    await adapter.on_trade_executed(event)

    kw = mock_gate.on_trade_closed.call_args.kwargs
    assert kw["period_start_balance"] == 9500.0
    assert kw["week_start_balance"]   == 9800.0
    assert kw["current_balance"]      == 9300.0


# ── Group 2: PostTradeHookProvider 프로토콜 ───────────────────────────────────

def test_safety_gate_adapter_satisfies_post_trade_hook_protocol():
    """SafetyGateAdapter는 PostTradeHookProvider 프로토콜을 만족해야 한다."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    adapter = SafetyGateAdapter(mock_gate)

    assert isinstance(adapter, PostTradeHookProvider), (
        "SafetyGateAdapter must implement PostTradeHookProvider protocol"
    )


# ── Group 3: Daily kill switch 누적 ──────────────────────────────────────────

def _mock_db_session(rowcount: int = 1):
    mock_result = MagicMock()
    mock_result.rowcount = rowcount
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.commit  = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_daily_kill_switch_triggers_after_on_trade_executed():
    """
    on_trade_executed 반복 호출 → DailyKillSwitch 손실 누적 → check_order_allowed 차단.

    daily_loss_limit_pct=0.03 (3%), 잔고=10000 → 한도=300 USDT
    max_loss_usdt=200 씩 2회 → 누적=400 > 300 → 트리거
    """
    from app.safety import InMemorySafetyStateStore, SafetyConfig, SafetyGate
    from app.safety.adapter import SafetyGateAdapter

    store   = InMemorySafetyStateStore()
    config  = SafetyConfig(live_trading_enabled=True, daily_loss_limit_pct=0.03)
    gate    = SafetyGate(store=store, config=config)
    adapter = SafetyGateAdapter(gate)
    user_id = str(uuid.uuid4())

    event = _make_event(
        user_id=user_id,
        max_loss_usdt=200.0,
        period_start=10000.0,
        week_start=10000.0,
        current=9800.0,
    )

    session = _mock_db_session()
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        # 1회: 200 누적 (한도 300 미달)
        await adapter.on_trade_executed(event)
        check1 = await gate.check_order_allowed(user_id)
        assert check1.allowed is True, "300 USDT 한도 미달 — 아직 허용 상태"

        # 2회: 400 누적 (한도 300 초과) → kill switch 발동
        await adapter.on_trade_executed(event)
    check2 = await gate.check_order_allowed(user_id)
    assert check2.allowed is False, "400 USDT > 300 USDT 한도 — 일일 kill switch 발동해야 함"
    assert check2.halt_reason is not None


# ── Group 4: Weekly kill switch 누적 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_weekly_kill_switch_triggers_after_on_trade_executed():
    """
    weekly_loss_limit_pct=0.05 (5%), 잔고=10000 → 한도=500 USDT
    max_loss_usdt=300 씩 2회 → 누적=600 > 500 → 트리거
    """
    from app.safety import InMemorySafetyStateStore, SafetyConfig, SafetyGate
    from app.safety.adapter import SafetyGateAdapter

    store   = InMemorySafetyStateStore()
    config  = SafetyConfig(
        live_trading_enabled=True,
        daily_loss_limit_pct=0.99,    # 일일 한도 무력화
        weekly_loss_limit_pct=0.05,
    )
    gate    = SafetyGate(store=store, config=config)
    adapter = SafetyGateAdapter(gate)
    user_id = str(uuid.uuid4())

    event = _make_event(
        user_id=user_id,
        max_loss_usdt=300.0,
        period_start=10000.0,
        week_start=10000.0,
        current=9700.0,
    )

    session = _mock_db_session()
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(event)
        check1 = await gate.check_order_allowed(user_id)
        assert check1.allowed is True

        await adapter.on_trade_executed(event)
    check2 = await gate.check_order_allowed(user_id)
    assert check2.allowed is False, "600 USDT > 500 USDT 한도 — 주간 kill switch 발동해야 함"


# ── Group 5: Pipeline hook 통합 ───────────────────────────────────────────────

def _make_pipeline_deps(
    post_trade_hook=None,
    executed: bool = True,
    tp_sl_failed: bool = False,
) -> OrchestratorDeps:
    """최소 mock deps로 OrchestratorDeps 구성.

    tp_sl_failed=True: EMERGENCY_CLOSED 시나리오 — hook 호출 검증용.
    executed=False:    paper 모드 — hook 미호출 검증용.
    """
    from agents.execution.models import FilledOrder, ExecutionResult

    entry_order = FilledOrder(
        exchange_order_id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        purpose="entry",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        avg_fill_price=Decimal("50000"),
        fee_usdt=Decimal("0.02"),
        filled_at=datetime.now(timezone.utc),
    )
    # EMERGENCY_CLOSED: 진입 $50000, 긴급 청산 $49800 → realized_pnl = -0.2 USDT
    emergency_close_order = FilledOrder(
        exchange_order_id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        purpose="emergency_close",
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        avg_fill_price=Decimal("49800"),
        fee_usdt=Decimal("0.02"),
        filled_at=datetime.now(timezone.utc),
    ) if tp_sl_failed else None

    exec_result = ExecutionResult(
        approved=True,
        executed=executed,
        mode="testnet" if executed else "paper",
        entry_order=entry_order if executed else None,
        tp_sl_failed=tp_sl_failed,
        emergency_close_order=emergency_close_order,
    )

    # ValidationResult mock
    validation = MagicMock()
    validation.approved = True
    validation.rejection_code = None
    validation.rejection_reason = None
    validation.warnings = []
    validation.quantity = Decimal("0.001")
    validation.final_leverage = 5
    validation.max_loss_usdt = Decimal("200")

    market_data = AsyncMock()
    market_data.get_snapshot = AsyncMock(return_value={
        "ohlcv": {},
        "current_price": 50000.0,
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

    risk = AsyncMock()
    risk.validate_candidate = AsyncMock(return_value=validation)

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
        post_trade_hook=post_trade_hook,
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


def _make_pipeline_input() -> "PipelineInput":
    from agents.orchestrator.models import PipelineInput
    from agents.risk.models import AccountState, UserContext

    user_ctx = MagicMock(spec=UserContext)
    user_ctx.user_id = str(uuid.uuid4())
    user_ctx.max_leverage = 20
    user_ctx.risk_per_trade_pct = Decimal("0.01")

    account = MagicMock(spec=AccountState)
    account.balance = Decimal("10000")

    return PipelineInput(
        coin="BTC",
        user_id=user_ctx.user_id,
        user_ctx=user_ctx,
        account_state=account,
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions=[],
        portfolio_account=None,
    )


@pytest.mark.asyncio
async def test_pipeline_calls_hook_on_emergency_closed():
    """EMERGENCY_CLOSED → post_trade_hook.on_trade_executed 정확히 1회 호출.

    M-03 fix: COMPLETED(미청산) 경로에서는 hook을 호출하지 않는다.
    즉시 청산(EMERGENCY_CLOSED)에서만 hook이 발동한다.
    """
    hook = AsyncMock()
    hook.on_trade_executed = AsyncMock()

    deps   = _make_pipeline_deps(post_trade_hook=hook, executed=True, tp_sl_failed=True)
    pipeline = OrchestratorPipeline(deps)
    result = await pipeline.run(_make_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    hook.on_trade_executed.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_skips_hook_when_not_executed():
    """executed=False (paper 모드) → hook 호출 안 됨."""
    hook = AsyncMock()
    hook.on_trade_executed = AsyncMock()

    deps   = _make_pipeline_deps(post_trade_hook=hook, executed=False)
    pipeline = OrchestratorPipeline(deps)
    result = await pipeline.run(_make_pipeline_input())

    assert result.status == PipelineStatus.COMPLETED
    hook.on_trade_executed.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_hook_exception_does_not_affect_result():
    """hook이 예외를 던져도 pipeline 결과는 EMERGENCY_CLOSED 유지 (격리)."""
    hook = AsyncMock()
    hook.on_trade_executed = AsyncMock(side_effect=RuntimeError("hook error"))

    deps   = _make_pipeline_deps(post_trade_hook=hook, executed=True, tp_sl_failed=True)
    pipeline = OrchestratorPipeline(deps)
    result = await pipeline.run(_make_pipeline_input())

    # hook 실패는 격리 — 파이프라인 결과에 영향 없음
    assert result.status == PipelineStatus.EMERGENCY_CLOSED


@pytest.mark.asyncio
async def test_pipeline_hook_receives_correct_post_trade_event():
    """EMERGENCY_CLOSED hook에 전달되는 PostTradeEvent 필드 검증 (M-03 fix).

    realized_pnl_usdt: fill price 기반 실제 P&L 포함 여부 확인.
    """
    received: list[PostTradeEvent] = []

    async def capture_hook(event: PostTradeEvent) -> None:
        received.append(event)

    hook = MagicMock()
    hook.on_trade_executed = capture_hook

    deps   = _make_pipeline_deps(post_trade_hook=hook, executed=True, tp_sl_failed=True)
    pipeline = OrchestratorPipeline(deps)
    inp    = _make_pipeline_input()
    await pipeline.run(inp)

    assert len(received) == 1
    ev = received[0]
    assert ev.user_id == inp.user_id
    assert ev.coin    == "BTC"
    assert ev.direction in ("LONG", "SHORT")
    assert ev.entry_price > 0
    assert ev.max_loss_usdt >= 0.0
    assert ev.current_balance == float(inp.account_state.balance)
    # M-03: 실제 P&L이 채워져야 함 (entry=$50000, exit=$49800 → -0.2 USDT)
    assert ev.realized_pnl_usdt is not None
    assert ev.realized_pnl_usdt == pytest.approx(-0.2)
