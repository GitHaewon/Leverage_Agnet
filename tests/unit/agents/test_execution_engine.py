"""
ExecutionEngine 파이프라인 테스트.

검증:
  [거부 케이스]
  - ValidationResult(approved=False) → ExecutionResult(approved=False, executed=False)
  - rejection_code / rejection_reason 전달
  - HOLD 시그널 거부

  [LIVE_TRADING gate]
  - approved=True + live_trading=False → executed=False, mode="paper"
  - paper 모드에서 gateway 호출 없음
  - paper 모드에서 validation 결과 보존
  - paper 모드에서 warnings 보존

  [주문 실행 — live_trading=True + MockGateway]
  - approved=True, executed=True
  - LONG: entry=BUY, tp=SELL, sl=SELL
  - SHORT: entry=SELL, tp=BUY, sl=BUY
  - entry order_type=MARKET, not reduce_only
  - tp order_type=TAKE_PROFIT_MARKET, reduce_only=True
  - sl order_type=STOP_MARKET, reduce_only=True
  - 정확히 3개 주문 발행
  - entry qty == validation.quantity
  - tp 가격 == signal.take_profit
  - sl 가격 == signal.stop_loss
  - result.entry_order 필드 채워짐
  - mode="testnet"

  [TP/SL 실패]
  - take_profit 주문 실패 → tp_sl_failed=True, executed=True, entry_order 보존
  - warnings 보존

  [시스템 오류]
  - validator 예외 → approved=False, code="SYSTEM_ERROR"

  [설정 유효성]
  - live_trading=True + mode="paper" → ValueError
  - validator 호출 횟수 추적
"""
from __future__ import annotations

import asyncio

import pytest

from agents.execution.engine import ExecutionEngine
from agents.execution.gateway import PaperGateway
from agents.decision.models import FinalAction, StrategyType

from tests.unit.agents._execution_fixtures import (
    MockGateway,
    StubRiskValidator,
    make_candidate_request,
    make_approved_validation,
    make_final_decision,
    make_rejected_validation,
    make_request,
    make_signal,
    make_trade_candidate,
)


def _run(coro):
    return asyncio.run(coro)


def _engine_paper(validation):
    """paper 모드 엔진 (live_trading=False)."""
    return ExecutionEngine(
        risk_validator=StubRiskValidator(validation),
        gateway=PaperGateway(),
        live_trading_enabled=False,
    )


def _engine_live(validation, gateway=None, mode="testnet"):
    """live 모드 엔진 (live_trading=True)."""
    gw = gateway or MockGateway()
    return ExecutionEngine(
        risk_validator=StubRiskValidator(validation),
        gateway=gw,
        live_trading_enabled=True,
        mode=mode,
    )


# ── 거부 케이스 ───────────────────────────────────────────────────────────────────

def test_rejected_validation_not_approved():
    engine = _engine_paper(make_rejected_validation("ORDER_004", "R:R 미달"))
    result = _run(engine.execute(make_request()))
    assert result.approved is False


def test_rejected_validation_not_executed():
    engine = _engine_paper(make_rejected_validation("ORDER_004", "R:R 미달"))
    result = _run(engine.execute(make_request()))
    assert result.executed is False


def test_rejected_result_has_rejection_code():
    engine = _engine_paper(make_rejected_validation("ORDER_001", "일일 손실 한도"))
    result = _run(engine.execute(make_request()))
    assert result.rejection_code == "ORDER_001"


def test_rejected_result_has_rejection_reason():
    engine = _engine_paper(make_rejected_validation("ORDER_001", "일일 손실 한도"))
    result = _run(engine.execute(make_request()))
    assert "일일 손실 한도" in result.rejection_reason


def test_hold_signal_rejected():
    """HOLD 시그널 → ValidationResult(approved=False, code="HOLD")."""
    engine = _engine_paper(
        make_rejected_validation("HOLD", "HOLD 시그널 — 실행 없음")
    )
    result = _run(engine.execute(make_request(signal=make_signal(direction="HOLD"))))
    assert result.approved is False
    assert result.rejection_code == "HOLD"


def test_rejected_entry_order_is_none():
    engine = _engine_paper(make_rejected_validation())
    result = _run(engine.execute(make_request()))
    assert result.entry_order is None


# ── LIVE_TRADING gate (paper 모드) ────────────────────────────────────────────────

def test_paper_mode_approved_not_executed():
    """approved=True이지만 live_trading=False → executed=False."""
    engine = _engine_paper(make_approved_validation())
    result = _run(engine.execute(make_request()))
    assert result.approved is True
    assert result.executed is False


def test_paper_mode_result_mode_is_paper():
    engine = _engine_paper(make_approved_validation())
    result = _run(engine.execute(make_request()))
    assert result.mode == "paper"


def test_paper_mode_no_gateway_calls():
    """live_trading=False → gateway.place_order() 호출 없음."""
    gw = MockGateway()
    engine = ExecutionEngine(
        risk_validator=StubRiskValidator(make_approved_validation()),
        gateway=gw,
        live_trading_enabled=False,
    )
    _run(engine.execute(make_request()))
    assert len(gw.recorded_orders) == 0


def test_paper_mode_validation_preserved():
    val = make_approved_validation(final_leverage=7)
    engine = _engine_paper(val)
    result = _run(engine.execute(make_request()))
    assert result.validation is not None
    assert result.validation.final_leverage == 7


def test_paper_mode_warnings_preserved():
    val = make_approved_validation(warnings=["LEVERAGE_CAPPED: 15x → 10x"])
    engine = _engine_paper(val)
    result = _run(engine.execute(make_request()))
    assert "LEVERAGE_CAPPED: 15x → 10x" in result.warnings


# ── 주문 실행 (live_trading=True) ─────────────────────────────────────────────────

def test_live_mode_approved_and_executed():
    result = _run(_engine_live(make_approved_validation()).execute(make_request()))
    assert result.approved is True
    assert result.executed is True


def test_live_mode_places_exactly_three_orders():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert len(gw.recorded_orders) == 3


def test_long_entry_side_is_buy():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(
        make_request(signal=make_signal(direction="LONG"))
    ))
    assert gw.first.side == "BUY"


def test_long_tp_side_is_sell():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(
        make_request(signal=make_signal(direction="LONG"))
    ))
    assert gw.second.side == "SELL"


def test_long_sl_side_is_sell():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(
        make_request(signal=make_signal(direction="LONG"))
    ))
    assert gw.third.side == "SELL"


def test_short_entry_side_is_sell():
    gw = MockGateway()
    signal = make_signal(
        direction="SHORT",
        entry_price=__import__("decimal").Decimal("67450"),
        take_profit=__import__("decimal").Decimal("65700"),
        stop_loss=__import__("decimal").Decimal("68300"),
    )
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(
        make_request(signal=signal)
    ))
    assert gw.first.side == "SELL"


def test_short_tp_side_is_buy():
    from decimal import Decimal
    gw = MockGateway()
    signal = make_signal(
        direction="SHORT",
        entry_price=Decimal("67450"),
        take_profit=Decimal("65700"),
        stop_loss=Decimal("68300"),
    )
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(
        make_request(signal=signal)
    ))
    assert gw.second.side == "BUY"


def test_short_sl_side_is_buy():
    from decimal import Decimal
    gw = MockGateway()
    signal = make_signal(
        direction="SHORT",
        entry_price=Decimal("67450"),
        take_profit=Decimal("65700"),
        stop_loss=Decimal("68300"),
    )
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(
        make_request(signal=signal)
    ))
    assert gw.third.side == "BUY"


def test_entry_order_type_is_market():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert gw.first.order_type == "MARKET"


def test_tp_order_type_is_take_profit_market():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert gw.second.order_type == "TAKE_PROFIT_MARKET"


def test_sl_order_type_is_stop_market():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert gw.third.order_type == "STOP_MARKET"


def test_entry_is_not_reduce_only():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert gw.first.reduce_only is False


def test_tp_is_reduce_only():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert gw.second.reduce_only is True


def test_sl_is_reduce_only():
    gw = MockGateway()
    _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert gw.third.reduce_only is True


def test_entry_quantity_matches_validation():
    from decimal import Decimal
    val = make_approved_validation(quantity=Decimal("0.00741"))
    gw = MockGateway()
    _run(_engine_live(val, gateway=gw).execute(make_request()))
    assert gw.first.quantity == Decimal("0.00741")


def test_result_entry_order_is_filled():
    result = _run(_engine_live(make_approved_validation()).execute(make_request()))
    assert result.entry_order is not None
    assert result.entry_order.purpose == "entry"


def test_result_mode_is_testnet():
    result = _run(_engine_live(make_approved_validation(), mode="testnet").execute(make_request()))
    assert result.mode == "testnet"


# ── TP/SL 실패 처리 ───────────────────────────────────────────────────────────────

def test_tp_failure_marks_tp_sl_failed():
    """TP 주문 실패 → tp_sl_failed=True, 실행은 완료(entry 체결 있음)."""
    gw = MockGateway(fail_on_purpose="take_profit")
    result = _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert result.tp_sl_failed is True


def test_tp_failure_entry_order_preserved():
    """TP 실패해도 entry_order는 기록됨."""
    gw = MockGateway(fail_on_purpose="take_profit")
    result = _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert result.entry_order is not None
    assert result.executed is True


def test_tp_failure_tp_order_is_none():
    gw = MockGateway(fail_on_purpose="take_profit")
    result = _run(_engine_live(make_approved_validation(), gateway=gw).execute(make_request()))
    assert result.tp_order is None


# ── 시스템 오류 ───────────────────────────────────────────────────────────────────

def test_validator_exception_returns_system_error():
    """Risk Validator 예외 → SYSTEM_ERROR 거부."""
    class BrokenValidator:
        async def validate(self, *args, **kwargs):
            raise RuntimeError("DB 연결 실패")

    engine = ExecutionEngine(
        risk_validator=BrokenValidator(),
        gateway=PaperGateway(),
        live_trading_enabled=False,
    )
    result = _run(engine.execute(make_request()))
    assert result.approved is False
    assert result.rejection_code == "SYSTEM_ERROR"


# ── 설정 유효성 ───────────────────────────────────────────────────────────────────

def test_live_true_with_paper_mode_raises():
    """live_trading=True + mode='paper' → ValueError."""
    with pytest.raises(ValueError, match="mode"):
        ExecutionEngine(
            risk_validator=StubRiskValidator(make_approved_validation()),
            gateway=PaperGateway(),
            live_trading_enabled=True,
            mode="paper",
        )


def test_validator_called_exactly_once():
    stub = StubRiskValidator(make_approved_validation())
    engine = ExecutionEngine(
        risk_validator=stub,
        gateway=PaperGateway(),
        live_trading_enabled=False,
    )
    _run(engine.execute(make_request()))
    assert stub.call_count == 1


# ── Deterministic TradeCandidate / FinalDecision alignment ───────────────────

def test_scalping_rr_1_3_approved_candidate_reaches_execution_path():
    candidate = make_trade_candidate(
        strategy_type=StrategyType.SCALPING,
        actual_rr=1.3,
        min_required_rr=1.2,
        expected_holding_minutes=5,
    )
    stub = StubRiskValidator(make_rejected_validation("ORDER_004", "legacy R:R 2.0 fail"))
    gw = MockGateway()
    engine = ExecutionEngine(stub, gw, live_trading_enabled=True, mode="testnet")

    result = _run(engine.execute(make_candidate_request(candidate)))

    assert result.approved is True
    assert result.executed is True
    assert len(gw.recorded_orders) == 3
    assert stub.call_count == 0


def test_intraday_rr_1_6_approved_candidate_reaches_execution_path():
    candidate = make_trade_candidate(
        strategy_type=StrategyType.INTRADAY,
        actual_rr=1.6,
        min_required_rr=1.5,
        expected_holding_minutes=30,
    )
    stub = StubRiskValidator(make_rejected_validation("ORDER_004", "legacy R:R 2.0 fail"))
    gw = MockGateway()
    engine = ExecutionEngine(stub, gw, live_trading_enabled=True, mode="testnet")

    result = _run(engine.execute(make_candidate_request(candidate)))

    assert result.approved is True
    assert result.executed is True
    assert len(gw.recorded_orders) == 3
    assert stub.call_count == 0


def test_trend_following_rr_2_0_approved_candidate_reaches_execution_path():
    candidate = make_trade_candidate(
        strategy_type=StrategyType.TREND_FOLLOWING,
        actual_rr=2.0,
        min_required_rr=2.0,
        expected_holding_minutes=120,
    )
    gw = MockGateway()
    engine = _engine_live(
        make_rejected_validation("ORDER_004", "legacy should not run"),
        gateway=gw,
    )

    result = _run(engine.execute(make_candidate_request(candidate)))

    assert result.approved is True
    assert result.executed is True
    assert len(gw.recorded_orders) == 3


def test_candidate_rejected_by_risk_never_reaches_execution():
    candidate = make_trade_candidate()
    validation = make_rejected_validation("ORDER_001", "risk rejected")
    gw = MockGateway()
    engine = _engine_live(make_approved_validation(), gateway=gw)

    result = _run(engine.execute(make_candidate_request(candidate, validation=validation)))

    assert result.approved is False
    assert result.executed is False
    assert result.rejection_code == "ORDER_001"
    assert len(gw.recorded_orders) == 0


def test_final_decision_hold_never_reaches_execution():
    candidate = make_trade_candidate()
    final_decision = make_final_decision(candidate, action=FinalAction.HOLD)
    gw = MockGateway()
    engine = _engine_live(make_approved_validation(), gateway=gw)

    result = _run(engine.execute(make_candidate_request(
        candidate,
        final_decision=final_decision,
    )))

    assert result.approved is False
    assert result.executed is False
    assert result.rejection_code == "FINAL_DECISION_HOLD"
    assert len(gw.recorded_orders) == 0


def test_missing_stop_loss_rejected_inside_execution():
    candidate = make_trade_candidate(stop_loss=None)
    gw = MockGateway()
    engine = _engine_live(make_approved_validation(), gateway=gw)

    result = _run(engine.execute(make_candidate_request(candidate)))

    assert result.approved is False
    assert result.rejection_code == "ORDER_003"
    assert len(gw.recorded_orders) == 0


def test_missing_take_profit_rejected_inside_execution():
    candidate = make_trade_candidate(take_profit=None)
    gw = MockGateway()
    engine = _engine_live(make_approved_validation(), gateway=gw)

    result = _run(engine.execute(make_candidate_request(candidate)))

    assert result.approved is False
    assert result.rejection_code == "TAKE_PROFIT_MISSING"
    assert len(gw.recorded_orders) == 0


def test_candidate_tp_sl_failure_still_triggers_emergency_close():
    candidate = make_trade_candidate(
        strategy_type=StrategyType.SCALPING,
        actual_rr=1.3,
        min_required_rr=1.2,
        expected_holding_minutes=5,
    )
    gw = MockGateway(fail_on_purpose="take_profit")
    engine = _engine_live(make_approved_validation(), gateway=gw)

    result = _run(engine.execute(make_candidate_request(candidate)))

    assert result.executed is True
    assert result.tp_sl_failed is True
    assert result.emergency_close_order is not None
    assert gw.recorded_orders[-1].purpose == "emergency_close"


def test_candidate_paper_mode_places_no_real_orders():
    candidate = make_trade_candidate(
        strategy_type=StrategyType.INTRADAY,
        actual_rr=1.6,
        min_required_rr=1.5,
    )
    gw = MockGateway()
    engine = ExecutionEngine(
        risk_validator=StubRiskValidator(make_rejected_validation()),
        gateway=gw,
        live_trading_enabled=False,
    )

    result = _run(engine.execute(make_candidate_request(candidate)))

    assert result.approved is True
    assert result.executed is False
    assert result.mode == "paper"
    assert len(gw.recorded_orders) == 0
