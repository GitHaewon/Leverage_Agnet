"""
M-04 단위 테스트 — EMERGENCY_CLOSED 발생 시 Telegram 알림 발송 보장

검증 항목:
  1.  EmergencyClosedEvent 포맷 — symbol / direction / 진입가 / 청산가 / 사유 / 시각
  2.  format_alert() EmergencyClosedEvent 라우팅 정상 작동
  3.  EMERGENCY_CLOSED → AlertDispatcher.dispatch() 1회 호출
  4.  EMERGENCY_CLOSED + alert_dispatcher=None → 예외 없이 정상 반환
  5.  EMERGENCY_CLOSED + dispatcher 예외 → EMERGENCY_CLOSED 그대로 반환 (격리)
  6.  dispatch()에 전달된 EmergencyClosedEvent 필드 검증 (symbol, direction, entry/exit price)
  7.  COMPLETED 경로 → dispatcher 호출 안 됨
  8.  FAILED (emergency_close_failed=True) 경로 → dispatcher 호출 안 됨
  9.  exit_price: emergency_close_order 없을 때 entry_price fallback
  10. LONG / SHORT direction 포맷 심볼 검증
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.alert.formatter import format_alert, format_emergency_closed
from agents.alert.models import EmergencyClosedEvent
from agents.execution.models import ExecutionResult, FilledOrder
from agents.orchestrator.models import PipelineInput, PipelineStatus


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

_NOW = datetime(2025, 6, 10, 12, 0, 0, tzinfo=timezone.utc)

_FIXED_USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _event(
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    entry: str = "50000",
    exit_: str = "49500",
    reason: str = "TP/SL 설정 실패 — 긴급 청산 완료",
) -> EmergencyClosedEvent:
    return EmergencyClosedEvent(
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry_price=Decimal(entry),
        exit_price=Decimal(exit_),
        reason=reason,
        triggered_at=_NOW,
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


def _make_pipeline_deps(exec_result: ExecutionResult, alert_dispatcher=None, hook=None):
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

    decision, reviewer = _decision_and_reviewer()

    validation_mock = MagicMock()
    validation_mock.approved         = True
    validation_mock.rejection_code   = None
    validation_mock.rejection_reason = None
    validation_mock.warnings         = []
    validation_mock.quantity         = Decimal("0.001")
    validation_mock.final_leverage   = 5
    validation_mock.max_loss_usdt    = Decimal("200")

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
        alert_dispatcher=alert_dispatcher,
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


def _emergency_closed_er(exit_price: Decimal = Decimal("49500")) -> ExecutionResult:
    return ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry", Decimal("50000")),
        tp_sl_failed=True,
        emergency_close_order=_filled("emergency_close", exit_price),
        emergency_close_failed=False,
    )


def _completed_er() -> ExecutionResult:
    return ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_order=_filled("take_profit"),
        sl_order=_filled("stop_loss"),
        tp_sl_failed=False,
    )


def _dispatcher() -> AsyncMock:
    d = AsyncMock()
    d.dispatch = AsyncMock(return_value=None)
    return d


# ── Group 1: 포맷터 단위 테스트 ───────────────────────────────────────────────

def test_format_emergency_closed_contains_required_fields():
    """포맷 출력에 symbol / 진입가 / 청산가 / 사유 / 시각 모두 포함."""
    ev  = _event()
    txt = format_emergency_closed(ev)

    assert "BTCUSDT"          in txt
    assert "LONG"             in txt
    assert "$50,000.00"       in txt   # entry_price
    assert "$49,500.00"       in txt   # exit_price
    assert "TP/SL 설정 실패"  in txt
    assert "2025-06-10"       in txt


def test_format_emergency_closed_long_shows_up_arrow():
    """LONG 방향 → ▲ 심볼 포함."""
    txt = format_emergency_closed(_event(direction="LONG"))
    assert "▲" in txt


def test_format_emergency_closed_short_shows_down_arrow():
    """SHORT 방향 → ▼ 심볼 포함."""
    txt = format_emergency_closed(_event(direction="SHORT", exit_="3050"))
    assert "▼" in txt


def test_format_alert_routes_emergency_closed():
    """format_alert() → EmergencyClosedEvent 라우팅 정상."""
    ev  = _event()
    txt = format_alert(ev)
    assert "긴급 청산 완료" in txt


def test_emergency_closed_event_type():
    """event_type 필드는 항상 'emergency_closed'."""
    ev = _event()
    assert ev.event_type == "emergency_closed"


# ── Group 2: 파이프라인 → 알림 호출 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_closed_calls_alert_dispatcher():
    """tp_sl_failed=True → alert_dispatcher.dispatch() 1회 호출."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    dispatcher = _dispatcher()
    deps = _make_pipeline_deps(_emergency_closed_er(), alert_dispatcher=dispatcher)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_emergency_closed_without_dispatcher_no_error():
    """alert_dispatcher=None → 예외 없이 EMERGENCY_CLOSED 반환."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    deps = _make_pipeline_deps(_emergency_closed_er(), alert_dispatcher=None)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED


@pytest.mark.asyncio
async def test_emergency_closed_dispatcher_exception_does_not_change_status():
    """dispatcher.dispatch() 예외 → EMERGENCY_CLOSED 그대로 반환 (격리)."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    dispatcher = _dispatcher()
    dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("telegram down"))

    deps = _make_pipeline_deps(_emergency_closed_er(), alert_dispatcher=dispatcher)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    dispatcher.dispatch.assert_awaited_once()


# ── Group 3: dispatch에 전달된 이벤트 검증 ───────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_closed_event_fields_passed_to_dispatcher():
    """dispatch()에 전달된 EmergencyClosedEvent 내용 검증."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    received: list[EmergencyClosedEvent] = []

    async def capture(event) -> None:
        received.append(event)

    dispatcher = MagicMock()
    dispatcher.dispatch = capture

    deps = _make_pipeline_deps(
        _emergency_closed_er(exit_price=Decimal("49500")),
        alert_dispatcher=dispatcher,
    )
    await OrchestratorPipeline(deps).run(_pipeline_input())

    assert len(received) == 1
    ev = received[0]
    assert isinstance(ev, EmergencyClosedEvent)
    assert ev.symbol        == "BTCUSDT"
    assert ev.direction     == "LONG"
    assert ev.entry_price   == Decimal("50000")
    assert ev.exit_price    == Decimal("49500")
    assert "TP/SL" in ev.reason
    assert ev.event_type    == "emergency_closed"


@pytest.mark.asyncio
async def test_exit_price_falls_back_to_entry_when_no_emergency_order():
    """emergency_close_order=None → exit_price = entry_price (fallback)."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry", Decimal("50000")),
        tp_sl_failed=True,
        emergency_close_order=None,   # 체결 기록 없음
        emergency_close_failed=False,
    )

    received: list[EmergencyClosedEvent] = []

    async def capture(event) -> None:
        received.append(event)

    dispatcher = MagicMock()
    dispatcher.dispatch = capture

    deps = _make_pipeline_deps(er, alert_dispatcher=dispatcher)
    await OrchestratorPipeline(deps).run(_pipeline_input())

    assert len(received) == 1
    assert received[0].exit_price == Decimal("50000")  # entry_price fallback


# ── Group 4: 회귀 방지 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_completed_path_does_not_call_dispatcher():
    """정상 완료(COMPLETED) 경로 → dispatcher 호출 안 됨."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    dispatcher = _dispatcher()
    deps = _make_pipeline_deps(_completed_er(), alert_dispatcher=dispatcher)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.COMPLETED
    dispatcher.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_path_does_not_call_dispatcher():
    """긴급 청산 실패(FAILED) 경로 → dispatcher 호출 안 됨."""
    from agents.orchestrator.pipeline import OrchestratorPipeline

    er = ExecutionResult(
        approved=True, executed=True, mode="testnet",
        entry_order=_filled("entry"),
        tp_sl_failed=True,
        emergency_close_failed=True,
    )
    dispatcher = _dispatcher()
    deps = _make_pipeline_deps(er, alert_dispatcher=dispatcher)
    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.FAILED
    dispatcher.dispatch.assert_not_awaited()


# ── Group 5: AlertDispatcher 통합 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alert_dispatcher_integration():
    """
    실제 AlertDispatcher + CaptureSender 통합:
    dispatch() → format_emergency_closed() → send() 호출 검증.
    """
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from agents.alert.dispatcher import AlertDispatcher

    sent: list[str] = []

    class CaptureSender:
        async def send(self, chat_id: str, text: str) -> None:
            sent.append(text)

    real_dispatcher = AlertDispatcher(sender=CaptureSender(), chat_id="test_chat_123")
    deps = _make_pipeline_deps(_emergency_closed_er(), alert_dispatcher=real_dispatcher)

    result = await OrchestratorPipeline(deps).run(_pipeline_input())

    assert result.status == PipelineStatus.EMERGENCY_CLOSED
    assert len(sent) == 1
    assert "긴급 청산 완료" in sent[0]
    assert "BTCUSDT"        in sent[0]
    assert "$50,000.00"     in sent[0]   # entry_price
    assert "$49,500.00"     in sent[0]   # exit_price
