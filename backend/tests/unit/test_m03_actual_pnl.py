"""
M-03 단위 테스트 — 실제 P&L 기반 kill switch 누적

검증 항목:
  1.  EMERGENCY_CLOSED LONG — realized_pnl_usdt = (exit - entry) * qty
  2.  EMERGENCY_CLOSED SHORT — realized_pnl_usdt = (entry - exit) * qty
  3.  EMERGENCY_CLOSED 수익 케이스 — realized_pnl_usdt > 0 → kill switch 누적 안 됨
  4.  EMERGENCY_CLOSED 손실 케이스 — realized_pnl_usdt < 0 → 실제 손실만 누적
  5.  emergency_close_order=None — realized_pnl_usdt=None → max_loss_usdt fallback 사용
  6.  COMPLETED 경로 — hook 호출 안 됨 (미실현 P&L 누적 금지)
  7.  Adapter: realized_pnl_usdt 있으면 우선 사용
  8.  Adapter: realized_pnl_usdt=None이면 -max_loss_usdt 사용
  9.  kill switch: EMERGENCY_CLOSED 실제 손실만으로 일일 한도 초과 여부 판정
  10. EMERGENCY_CLOSED 수익 후 동일 사용자 다음 주문 → kill switch 발동 안 됨 (회귀 방지)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.execution.models import ExecutionResult, FilledOrder
from agents.orchestrator.models import PipelineInput, PipelineStatus, PostTradeEvent


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

_FIXED_USER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


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
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions=[],
        portfolio_account=None,
    )


def _make_pipeline_deps(exec_result: ExecutionResult, hook=None):
    from agents.orchestrator.pipeline import OrchestratorDeps

    market_data = AsyncMock()
    market_data.get_snapshot = AsyncMock(return_value={"ohlcv": {}, "current_price": 50000.0})

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

    analyst_result = MagicMock()
    analyst_result.is_actionable = True
    analyst_result.hold_reason   = None
    analyst_result.decision      = MagicMock(decision="LONG", confidence=80)
    analyst_result.entry_price   = 50000.0
    analyst_result.take_profit   = 55000.0
    analyst_result.stop_loss     = 48000.0
    analyst_result.leverage      = 5

    analyst = AsyncMock()
    analyst.analyze = AsyncMock(return_value=analyst_result)

    validation_mock = MagicMock()
    validation_mock.approved         = True
    validation_mock.rejection_code   = None
    validation_mock.rejection_reason = None
    validation_mock.warnings         = []
    validation_mock.quantity         = Decimal("0.001")
    validation_mock.final_leverage   = 5
    validation_mock.max_loss_usdt    = Decimal("200")

    risk = AsyncMock()
    risk.validate = AsyncMock(return_value=validation_mock)

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
        analyst=analyst,
        risk=risk,
        portfolio=portfolio,
        position_manager=position_manager,
        execution=execution,
        post_trade_hook=hook,
    )


def _mock_db_session(rowcount: int = 0):
    mock_result = MagicMock()
    mock_result.rowcount = rowcount
    session = AsyncMock()
    session.execute  = AsyncMock(return_value=mock_result)
    session.commit   = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=None)
    return session


# ── Group 1: realized_pnl_usdt 계산 정확도 ────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_closed_long_realized_pnl():
    """LONG 긴급 청산 — realized_pnl = (exit - entry) * qty."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    received: list[PostTradeEvent] = []

    async def capture(event: PostTradeEvent) -> None:
        received.append(event)

    hook = MagicMock()
    hook.on_trade_executed = capture

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry",          Decimal("50000")),
        tp_sl_failed=True,
        emergency_close_order=_filled("emergency_close", Decimal("49800")),
        emergency_close_failed=False,
    )
    deps = _make_pipeline_deps(er, hook=hook)
    await OrchestratorPipeline(deps).run(_pipeline_input())

    assert len(received) == 1
    ev = received[0]
    # (49800 - 50000) * 0.001 = -0.2 USDT
    assert ev.realized_pnl_usdt == pytest.approx(-0.2)


@pytest.mark.asyncio
async def test_emergency_closed_short_realized_pnl():
    """SHORT 긴급 청산 — realized_pnl = (entry - exit) * qty."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    received: list[PostTradeEvent] = []

    async def capture(event: PostTradeEvent) -> None:
        received.append(event)

    hook = MagicMock()
    hook.on_trade_executed = capture

    # SHORT: 진입 3000, 청산 3050 (불리한 청산 → 손실)
    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=FilledOrder(
            exchange_order_id=str(uuid.uuid4()),
            symbol="ETHUSDT",
            purpose="entry",  # type: ignore[arg-type]
            side="SELL",
            order_type="MARKET",
            quantity=Decimal("0.01"),
            avg_fill_price=Decimal("3000"),
            fee_usdt=Decimal("0.01"),
            filled_at=datetime.now(timezone.utc),
        ),
        tp_sl_failed=True,
        emergency_close_order=FilledOrder(
            exchange_order_id=str(uuid.uuid4()),
            symbol="ETHUSDT",
            purpose="emergency_close",  # type: ignore[arg-type]
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("0.01"),
            avg_fill_price=Decimal("3050"),
            fee_usdt=Decimal("0.01"),
            filled_at=datetime.now(timezone.utc),
        ),
        emergency_close_failed=False,
    )

    # analyst가 SHORT를 반환하도록 패치
    from agents.orchestrator.pipeline import OrchestratorDeps
    deps = _make_pipeline_deps(er, hook=hook)
    # analyst_result.decision.decision은 기본 "LONG" — SHORT는 raw_signal에 반영됨
    # direction은 _fire_post_trade_hook에서 raw_signal.direction 사용
    # 테스트를 위해 analyst를 SHORT로 교체
    analyst_short = MagicMock()
    analyst_short.is_actionable = True
    analyst_short.hold_reason   = None
    analyst_short.decision      = MagicMock(decision="SHORT", confidence=80)
    analyst_short.entry_price   = 3000.0
    analyst_short.take_profit   = 2700.0
    analyst_short.stop_loss     = 3150.0
    analyst_short.leverage      = 3
    deps.analyst.analyze = AsyncMock(return_value=analyst_short)

    await OrchestratorPipeline(deps).run(_pipeline_input())

    assert len(received) == 1
    ev = received[0]
    # SHORT: (3000 - 3050) * 0.01 = -0.5 USDT
    assert ev.realized_pnl_usdt == pytest.approx(-0.5)


@pytest.mark.asyncio
async def test_emergency_closed_profitable_long():
    """LONG 긴급 청산이 수익일 때 — realized_pnl > 0."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    received: list[PostTradeEvent] = []

    async def capture(event: PostTradeEvent) -> None:
        received.append(event)

    hook = MagicMock()
    hook.on_trade_executed = capture

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry",          Decimal("50000")),
        tp_sl_failed=True,
        emergency_close_order=_filled("emergency_close", Decimal("50200")),
        emergency_close_failed=False,
    )
    deps = _make_pipeline_deps(er, hook=hook)
    await OrchestratorPipeline(deps).run(_pipeline_input())

    # (50200 - 50000) * 0.001 = +0.2 USDT
    assert received[0].realized_pnl_usdt == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_no_emergency_close_order_uses_none():
    """emergency_close_order=None → realized_pnl_usdt=None (max_loss_usdt fallback)."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    received: list[PostTradeEvent] = []

    async def capture(event: PostTradeEvent) -> None:
        received.append(event)

    hook = MagicMock()
    hook.on_trade_executed = capture

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry", Decimal("50000")),
        tp_sl_failed=True,
        emergency_close_order=None,
        emergency_close_failed=False,
    )
    deps = _make_pipeline_deps(er, hook=hook)
    await OrchestratorPipeline(deps).run(_pipeline_input())

    assert received[0].realized_pnl_usdt is None
    assert received[0].max_loss_usdt == pytest.approx(200.0)


# ── Group 2: COMPLETED 경로 — hook 미호출 ────────────────────────────────────

@pytest.mark.asyncio
async def test_completed_path_hook_not_called():
    """COMPLETED(TP/SL 설정 완료) → hook 호출 안 됨. 미실현 P&L 누적 금지."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    hook = AsyncMock()
    hook.on_trade_executed = AsyncMock()

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_order=_filled("take_profit"),
        sl_order=_filled("stop_loss"),
        tp_sl_failed=False,
    )
    deps = _make_pipeline_deps(er, hook=hook)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.COMPLETED
    hook.on_trade_executed.assert_not_awaited()


# ── Group 3: Adapter 우선순위 검증 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_uses_realized_pnl_when_set():
    """realized_pnl_usdt 있으면 on_trade_closed()에 이 값 사용."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[])

    adapter = SafetyGateAdapter(gate=mock_gate)
    event = PostTradeEvent(
        user_id=_FIXED_USER_ID,
        coin="BTC",
        direction="LONG",
        entry_price=Decimal("50000"),
        quantity=Decimal("0.001"),
        stop_loss=Decimal("48000"),
        max_loss_usdt=200.0,
        realized_pnl_usdt=-0.2,   # 실제 손실 0.2 USDT
        period_start_balance=10000.0,
        week_start_balance=10000.0,
        current_balance=10000.0,
    )

    session = _mock_db_session(rowcount=0)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(event)

    call_kwargs = mock_gate.on_trade_closed.call_args
    # pnl_usdt = realized_pnl_usdt = -0.2 (not -max_loss_usdt = -200.0)
    assert call_kwargs.kwargs["pnl_usdt"] == pytest.approx(-0.2)


@pytest.mark.asyncio
async def test_adapter_falls_back_to_max_loss_when_no_realized_pnl():
    """realized_pnl_usdt=None → on_trade_closed()에 -max_loss_usdt 사용."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[])

    adapter = SafetyGateAdapter(gate=mock_gate)
    event = PostTradeEvent(
        user_id=_FIXED_USER_ID,
        coin="BTC",
        direction="LONG",
        entry_price=Decimal("50000"),
        quantity=Decimal("0.001"),
        stop_loss=Decimal("48000"),
        max_loss_usdt=200.0,
        realized_pnl_usdt=None,    # fallback
        period_start_balance=10000.0,
        week_start_balance=10000.0,
        current_balance=10000.0,
    )

    session = _mock_db_session(rowcount=0)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(event)

    call_kwargs = mock_gate.on_trade_closed.call_args
    # pnl_usdt = -max_loss_usdt = -200.0
    assert call_kwargs.kwargs["pnl_usdt"] == pytest.approx(-200.0)


# ── Group 4: 수익 거래 후 kill switch 미발동 ─────────────────────────────────

@pytest.mark.asyncio
async def test_profitable_emergency_close_does_not_accumulate_loss():
    """EMERGENCY_CLOSED 수익(realized_pnl > 0) → kill switch 손실 0 누적."""
    from app.safety import InMemorySafetyStateStore, SafetyConfig, SafetyGate
    from app.safety.adapter import SafetyGateAdapter

    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    adapter = SafetyGateAdapter(gate=gate)

    # 수익 거래 이벤트
    event = PostTradeEvent(
        user_id=_FIXED_USER_ID,
        coin="BTC",
        direction="LONG",
        entry_price=Decimal("50000"),
        quantity=Decimal("0.001"),
        stop_loss=Decimal("48000"),
        max_loss_usdt=200.0,
        realized_pnl_usdt=+5.0,   # 수익!
        period_start_balance=10000.0,
        week_start_balance=10000.0,
        current_balance=10005.0,
    )

    session = _mock_db_session(rowcount=0)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(event)

    # 수익이므로 daily kill switch 발동 안 됨
    daily_state = await store.get_daily_kill_switch(_FIXED_USER_ID)
    assert daily_state.is_halted is False


@pytest.mark.asyncio
async def test_loss_emergency_close_accumulates_only_actual_loss():
    """EMERGENCY_CLOSED 손실 → 실제 손실(0.2 USDT)만 누적, max_loss(200 USDT) 아님."""
    from app.safety import InMemorySafetyStateStore, SafetyConfig, SafetyGate
    from app.safety.adapter import SafetyGateAdapter
    from app.safety.kill_switch import DailyKillSwitch

    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    adapter = SafetyGateAdapter(gate=gate)

    # 소폭 손실 거래 — 실제 0.2 USDT 손실, max_loss는 200 USDT
    event = PostTradeEvent(
        user_id=_FIXED_USER_ID,
        coin="BTC",
        direction="LONG",
        entry_price=Decimal("50000"),
        quantity=Decimal("0.001"),
        stop_loss=Decimal("48000"),
        max_loss_usdt=200.0,       # 구 방식 → 200 USDT 누적 (잘못됨)
        realized_pnl_usdt=-0.2,   # 신 방식 → 0.2 USDT 누적 (올바름)
        period_start_balance=10000.0,
        week_start_balance=10000.0,
        current_balance=9999.8,
    )

    session = _mock_db_session(rowcount=0)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(event)

    # kill switch: 일일 한도 기본값 = 100 USDT
    # 0.2 USDT 손실 → 한도 미초과 → 발동 안 됨
    daily_state = await store.get_daily_kill_switch(_FIXED_USER_ID)
    assert daily_state.is_halted is False
