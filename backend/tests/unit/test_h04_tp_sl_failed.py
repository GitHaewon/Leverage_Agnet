"""
H-04 단위 테스트 — tp_sl_failed=True 처리 보장.

검증 항목:
  1. TP/SL 성공 → tp_sl_failed=False, normal ExecutionResult
  2. TP/SL 실패 후 재시도 성공 → tp_sl_failed=False (정상 완료)
  3. TP/SL 실패 후 재시도 실패 → 긴급 청산 실행 → tp_sl_failed=True, emergency_close_order 설정
  4. 긴급 청산도 실패 → emergency_close_failed=True
  5. 재시도 중 TP는 성공하고 SL만 실패할 때 SL만 재시도
  6. build_emergency_close_ticket 주문 속성 검증
  7. Pipeline: emergency_close_failed=True → PipelineStatus.FAILED
  8. Pipeline: tp_sl_failed=True, 긴급 청산 성공 → PipelineStatus.EMERGENCY_CLOSED
  9. Pipeline: 정상 실행 → PipelineStatus.COMPLETED (tp_sl_failed 미발생)
  10. 긴급 청산 주문 purpose="emergency_close", reduce_only=True, MARKET
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agents.execution.engine import (
    ExecutionEngine,
    build_emergency_close_ticket,
    build_entry_ticket,
    build_sl_ticket,
    build_tp_ticket,
)
from agents.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    FilledOrder,
    OrderTicket,
)
from agents.orchestrator.models import PipelineStatus
from agents.risk.models import AccountState, RawSignal, UserContext, ValidationResult


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

def _signal() -> RawSignal:
    return RawSignal(
        coin="BTC",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        take_profit=Decimal("55000"),
        stop_loss=Decimal("48000"),
        confidence=0.85,
        leverage=5,
    )


def _short_signal() -> RawSignal:
    return RawSignal(
        coin="ETH",
        symbol="ETHUSDT",
        direction="SHORT",
        entry_price=Decimal("3000"),
        take_profit=Decimal("2700"),
        stop_loss=Decimal("3150"),
        confidence=0.80,
        leverage=3,
    )


def _user_ctx() -> UserContext:
    ctx = MagicMock(spec=UserContext)
    ctx.user_id = str(uuid.uuid4())
    ctx.max_leverage = 20
    ctx.risk_per_trade_pct = Decimal("0.01")
    return ctx


def _account() -> AccountState:
    acc = MagicMock(spec=AccountState)
    acc.balance = Decimal("10000")
    return acc


def _validation() -> ValidationResult:
    v = MagicMock(spec=ValidationResult)
    v.approved = True
    v.quantity = Decimal("0.001")
    v.final_leverage = 5
    v.rejection_code = None
    v.rejection_reason = None
    v.warnings = []
    return v


def _make_req(signal: RawSignal | None = None) -> ExecutionRequest:
    return ExecutionRequest(
        signal=signal or _signal(),
        user_ctx=_user_ctx(),
        account=_account(),
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions_count=0,
        same_coin_position=None,
    )


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


def _engine(gateway: AsyncMock) -> ExecutionEngine:
    risk = AsyncMock()
    risk.validate = AsyncMock(return_value=_validation())
    return ExecutionEngine(
        risk_validator=risk,
        gateway=gateway,
        live_trading_enabled=True,
        mode="testnet",
        safety_gate=_allow_gate(),
    )


def _allow_gate() -> AsyncMock:
    from agents.execution.models import SafetyDecision
    gate = AsyncMock()
    gate.check_order_allowed = AsyncMock(return_value=SafetyDecision(allowed=True))
    return gate


# ── Group 1: 정상 실행 (TP/SL 성공) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_normal_execution_tp_sl_success():
    """TP/SL 성공 → tp_sl_failed=False, tp_order/sl_order 설정."""
    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=[
        _filled("entry"),
        _filled("take_profit", Decimal("55000")),
        _filled("stop_loss",   Decimal("48000")),
    ])
    engine = _engine(gw)
    result = await engine.execute(_make_req())

    assert result.executed is True
    assert result.tp_sl_failed is False
    assert result.tp_order is not None
    assert result.sl_order is not None
    assert result.emergency_close_order is None
    assert result.emergency_close_failed is False
    assert gw.place_order.await_count == 3   # entry + TP + SL


# ── Group 2: TP/SL 실패 후 재시도 성공 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_tp_sl_retry_succeeds():
    """1차 TP 실패 → 재시도 성공 → tp_sl_failed=False."""
    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=[
        _filled("entry"),               # 진입 성공
        Exception("TP order failed"),   # 1차 TP 실패
        _filled("take_profit"),         # 재시도 TP 성공
        _filled("stop_loss"),           # 재시도 SL 성공
    ])
    engine = _engine(gw)
    result = await engine.execute(_make_req())

    assert result.executed is True
    assert result.tp_sl_failed is False
    assert result.tp_order is not None
    assert result.sl_order is not None
    assert result.emergency_close_order is None
    assert gw.place_order.await_count == 4   # entry + (fail TP) + retry TP + retry SL


@pytest.mark.asyncio
async def test_tp_success_sl_fails_sl_retried():
    """TP 성공 → SL 실패 → 재시도에서 SL만 재시도."""
    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=[
        _filled("entry"),               # 진입 성공
        _filled("take_profit"),         # TP 성공
        Exception("SL order failed"),   # SL 실패 (TP는 이미 있음)
        _filled("stop_loss"),           # SL 재시도 성공
    ])
    engine = _engine(gw)
    result = await engine.execute(_make_req())

    assert result.executed is True
    assert result.tp_sl_failed is False
    assert result.tp_order is not None
    assert result.sl_order is not None


# ── Group 3: TP/SL 재시도 실패 → 긴급 청산 ──────────────────────────────────

@pytest.mark.asyncio
async def test_tp_sl_retry_fails_triggers_emergency_close():
    """재시도 실패 → 긴급 청산 실행 → emergency_close_order 설정."""
    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=[
        _filled("entry"),                   # 진입 성공
        Exception("TP failed 1st"),         # 1차 TP 실패
        Exception("TP failed retry"),       # 재시도 TP 실패
        _filled("emergency_close"),         # 긴급 청산 성공
    ])
    engine = _engine(gw)
    result = await engine.execute(_make_req())

    assert result.executed is True
    assert result.tp_sl_failed is True
    assert result.emergency_close_order is not None
    assert result.emergency_close_failed is False
    assert result.tp_order is None
    assert result.sl_order is None


@pytest.mark.asyncio
async def test_emergency_close_is_market_reduce_only():
    """긴급 청산 주문 — MARKET, reduce_only=True, purpose=emergency_close."""
    placed_tickets: list[OrderTicket] = []
    responses = [
        _filled("entry"),
        Exception("TP fail 1"),
        Exception("TP fail retry"),
        _filled("emergency_close"),
    ]
    response_iter = iter(responses)

    async def side_effect(ticket: OrderTicket) -> FilledOrder:
        placed_tickets.append(ticket)
        resp = next(response_iter)
        if isinstance(resp, Exception):
            raise resp
        return resp

    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=side_effect)
    engine = _engine(gw)
    result = await engine.execute(_make_req())

    # 마지막 호출이 긴급 청산 주문
    emergency_ticket = placed_tickets[-1]
    assert emergency_ticket.purpose == "emergency_close"
    assert emergency_ticket.order_type == "MARKET"
    assert emergency_ticket.reduce_only is True
    assert emergency_ticket.side == "SELL"   # LONG 포지션 청산 = SELL


# ── Group 4: 긴급 청산도 실패 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_close_also_fails():
    """긴급 청산도 실패 → emergency_close_failed=True, emergency_close_order=None."""
    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=[
        _filled("entry"),
        Exception("TP fail 1"),
        Exception("TP fail retry"),
        Exception("Emergency close FAILED"),
    ])
    engine = _engine(gw)
    result = await engine.execute(_make_req())

    assert result.executed is True
    assert result.tp_sl_failed is True
    assert result.emergency_close_order is None
    assert result.emergency_close_failed is True


@pytest.mark.asyncio
async def test_emergency_close_fails_logs_critical(caplog):
    """긴급 청산 실패 시 CRITICAL 로그 출력."""
    import logging
    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=[
        _filled("entry"),
        Exception("TP fail"),
        Exception("TP retry fail"),
        Exception("Emergency close FAILED"),
    ])
    engine = _engine(gw)

    with caplog.at_level(logging.CRITICAL, logger="agents.execution.engine"):
        await engine.execute(_make_req())

    assert "EMERGENCY_CLOSE_FAILED" in caplog.text


# ── Group 5: build_emergency_close_ticket ────────────────────────────────────

def test_emergency_close_ticket_long():
    """LONG 포지션 긴급 청산 → SELL, MARKET."""
    ticket = build_emergency_close_ticket(_signal(), Decimal("0.005"))

    assert ticket.purpose == "emergency_close"
    assert ticket.order_type == "MARKET"
    assert ticket.reduce_only is True
    assert ticket.side == "SELL"
    assert ticket.quantity == Decimal("0.005")
    assert ticket.symbol == "BTCUSDT"


def test_emergency_close_ticket_short():
    """SHORT 포지션 긴급 청산 → BUY, MARKET."""
    ticket = build_emergency_close_ticket(_short_signal(), Decimal("0.1"))

    assert ticket.purpose == "emergency_close"
    assert ticket.order_type == "MARKET"
    assert ticket.reduce_only is True
    assert ticket.side == "BUY"
    assert ticket.symbol == "ETHUSDT"


# ── Group 6: Pipeline 통합 테스트 ─────────────────────────────────────────────

def _make_pipeline_deps(exec_result: ExecutionResult):
    """최소 pipeline deps — ExecutionEngine을 주어진 result를 반환하도록 stub."""
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
    validation_mock.approved = True
    validation_mock.rejection_code = None
    validation_mock.rejection_reason = None
    validation_mock.warnings = []
    validation_mock.quantity = Decimal("0.001")
    validation_mock.final_leverage = 5
    validation_mock.max_loss_usdt = Decimal("200")

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


def _pipeline_input():
    from agents.orchestrator.models import PipelineInput
    user_ctx = MagicMock()
    user_ctx.user_id = str(uuid.uuid4())
    user_ctx.max_leverage = 20
    user_ctx.risk_per_trade_pct = Decimal("0.01")
    account = MagicMock()
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
async def test_pipeline_emergency_close_failed_returns_failed():
    """긴급 청산 실패 → PipelineStatus.FAILED."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_sl_failed=True,
        emergency_close_failed=True,
    )
    deps = _make_pipeline_deps(er)
    pipeline = OrchestratorPipeline(deps)
    result = await pipeline.run(_pipeline_input())

    assert result.status == PipelineStatus.FAILED
    assert "긴급 청산 실패" in (result.rejection_reason or "")


@pytest.mark.asyncio
async def test_pipeline_emergency_close_success_returns_emergency_closed():
    """긴급 청산 성공 → PipelineStatus.EMERGENCY_CLOSED."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_sl_failed=True,
        emergency_close_order=_filled("emergency_close"),
        emergency_close_failed=False,
    )
    deps = _make_pipeline_deps(er)
    pipeline = OrchestratorPipeline(deps)
    result = await pipeline.run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    assert "긴급 청산" in (result.rejection_reason or "")


@pytest.mark.asyncio
async def test_pipeline_normal_execution_returns_completed():
    """정상 실행(TP/SL 성공) → PipelineStatus.COMPLETED."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_order=_filled("take_profit"),
        sl_order=_filled("stop_loss"),
        tp_sl_failed=False,
    )
    deps = _make_pipeline_deps(er)
    pipeline = OrchestratorPipeline(deps)
    result = await pipeline.run(_pipeline_input())

    assert result.status == PipelineStatus.COMPLETED
