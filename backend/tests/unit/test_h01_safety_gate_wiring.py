"""
H-01 단위 테스트 — ExecutionEngine + SafetyGate 연결.

검증 항목:
  1. SafetyGate 허용 → 주문 실행 (gateway.place_order 호출됨)
  2. SafetyGate 거부 → 주문 차단 (gateway.place_order 호출 안 됨)
  3. SafetyGate 없음(None) + live mode → 경고 로그, 주문은 실행됨
  4. Paper 모드 → SafetyGate 호출 안 됨 (LIVE_TRADING_ENABLED=false에서 종료)
  5. SafetyGateAdapter — SafetyCheckResult → SafetyDecision 변환
  6. 거부 시 ExecutionResult.rejection_code = halt_reason 값
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.execution.engine import ExecutionEngine
from agents.execution.models import (
    ExecutionRequest,
    FilledOrder,
    SafetyDecision,
    SafetyGateProtocol,
)
from agents.risk.models import (
    AccountState,
    OpenPosition,
    RawSignal,
    UserContext,
    ValidationResult,
)


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
        reason="test signal",
        rr_ratio=2.5,
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


def _validation_approved() -> ValidationResult:
    v = MagicMock(spec=ValidationResult)
    v.approved = True
    v.quantity = Decimal("0.001")
    v.final_leverage = 5
    v.rejection_code = None
    v.rejection_reason = None
    v.warnings = []
    return v


def _filled_order(purpose: str = "entry") -> FilledOrder:
    return FilledOrder(
        exchange_order_id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        purpose=purpose,  # type: ignore[arg-type]
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        avg_fill_price=Decimal("50000"),
        fee_usdt=Decimal("0.02"),
        filled_at=datetime.now(timezone.utc),
    )


def _make_req() -> ExecutionRequest:
    return ExecutionRequest(
        signal=_signal(),
        user_ctx=_user_ctx(),
        account=_account(),
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions_count=0,
        same_coin_position=None,
    )


def _stub_risk_validator(approved: bool = True) -> AsyncMock:
    validator = AsyncMock()
    validator.validate = AsyncMock(return_value=_validation_approved() if approved else _validation_rejected())
    return validator


def _validation_rejected() -> ValidationResult:
    v = MagicMock(spec=ValidationResult)
    v.approved = False
    v.rejection_code = "HOLD_SIGNAL"
    v.rejection_reason = "Signal direction is HOLD"
    v.warnings = []
    return v


def _stub_gateway() -> AsyncMock:
    gw = AsyncMock()
    gw.place_order = AsyncMock(side_effect=[
        _filled_order("entry"),
        _filled_order("take_profit"),
        _filled_order("stop_loss"),
    ])
    gw.cancel_all_orders = AsyncMock(return_value=0)
    return gw


def _stub_safety_gate(allowed: bool, code: str | None = None) -> AsyncMock:
    gate = AsyncMock()
    gate.check_order_allowed = AsyncMock(
        return_value=SafetyDecision(
            allowed=allowed,
            rejection_code=code,
            message="test" if not allowed else "",
        )
    )
    return gate


# ── 핵심 불변식 테스트 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_safety_gate_allowed_executes_order():
    """SafetyGate 허용 → gateway.place_order 호출됨."""
    gw = _stub_gateway()
    engine = ExecutionEngine(
        risk_validator=_stub_risk_validator(approved=True),
        gateway=gw,
        live_trading_enabled=True,
        mode="testnet",
        safety_gate=_stub_safety_gate(allowed=True),
    )
    result = await engine.execute(_make_req())

    assert result.approved is True
    assert result.executed is True
    assert gw.place_order.await_count == 3  # entry + TP + SL


@pytest.mark.asyncio
async def test_safety_gate_denied_blocks_order():
    """SafetyGate 거부 → gateway.place_order 절대 호출 안 됨."""
    gw = _stub_gateway()
    engine = ExecutionEngine(
        risk_validator=_stub_risk_validator(approved=True),
        gateway=gw,
        live_trading_enabled=True,
        mode="testnet",
        safety_gate=_stub_safety_gate(allowed=False, code="DAILY_LOSS_LIMIT"),
    )
    result = await engine.execute(_make_req())

    assert result.approved is False
    assert result.executed is False
    assert result.rejection_code == "DAILY_LOSS_LIMIT"
    gw.place_order.assert_not_awaited()   # 핵심 안전 불변식


@pytest.mark.asyncio
async def test_safety_gate_denied_after_risk_approved():
    """Risk 통과 + SafetyGate 거부 → 주문 차단 (Safety Layer가 최후 방어선)."""
    gw = _stub_gateway()
    engine = ExecutionEngine(
        risk_validator=_stub_risk_validator(approved=True),
        gateway=gw,
        live_trading_enabled=True,
        mode="testnet",
        safety_gate=_stub_safety_gate(allowed=False, code="EMERGENCY_SHUTDOWN"),
    )
    result = await engine.execute(_make_req())

    assert result.approved is False
    assert result.rejection_code == "EMERGENCY_SHUTDOWN"
    gw.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_risk_rejected_skips_safety_gate():
    """Risk 거부 → SafetyGate 호출 안 됨 (STEP 1에서 종료)."""
    gw = _stub_gateway()
    safety = _stub_safety_gate(allowed=True)
    engine = ExecutionEngine(
        risk_validator=_stub_risk_validator(approved=False),
        gateway=gw,
        live_trading_enabled=True,
        mode="testnet",
        safety_gate=safety,
    )
    await engine.execute(_make_req())

    safety.check_order_allowed.assert_not_awaited()
    gw.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_paper_mode_safety_gate_not_called():
    """Paper 모드 → SafetyGate 호출 안 됨 (STEP 2에서 종료)."""
    gw = _stub_gateway()
    safety = _stub_safety_gate(allowed=True)
    engine = ExecutionEngine(
        risk_validator=_stub_risk_validator(approved=True),
        gateway=gw,
        live_trading_enabled=False,
        mode="paper",
        safety_gate=safety,
    )
    result = await engine.execute(_make_req())

    assert result.approved is True
    assert result.executed is False   # paper 모드
    safety.check_order_allowed.assert_not_awaited()
    gw.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_safety_gate_none_live_mode_warns_but_executes(caplog):
    """safety_gate=None + live 모드 → 경고 로그 출력, 주문은 실행됨."""
    import logging
    gw = _stub_gateway()
    with caplog.at_level(logging.WARNING, logger="agents.execution.engine"):
        engine = ExecutionEngine(
            risk_validator=_stub_risk_validator(approved=True),
            gateway=gw,
            live_trading_enabled=True,
            mode="testnet",
            safety_gate=None,
        )

    assert "safety_gate is None" in caplog.text
    result = await engine.execute(_make_req())
    assert result.executed is True


@pytest.mark.asyncio
async def test_safety_gate_rejection_code_fallback():
    """rejection_code=None 이면 SAFETY_GATE_BLOCKED 기본값 사용."""
    gw = _stub_gateway()
    engine = ExecutionEngine(
        risk_validator=_stub_risk_validator(approved=True),
        gateway=gw,
        live_trading_enabled=True,
        mode="testnet",
        safety_gate=_stub_safety_gate(allowed=False, code=None),
    )
    result = await engine.execute(_make_req())

    assert result.rejection_code == "SAFETY_GATE_BLOCKED"
    gw.place_order.assert_not_awaited()


# ── SafetyGateAdapter 단위 테스트 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_converts_allowed_result():
    """SafetyCheckResult(allowed=True) → SafetyDecision(allowed=True)."""
    from app.safety.adapter import SafetyGateAdapter
    from app.safety.types import SafetyCheckResult

    mock_gate = AsyncMock()
    mock_gate.check_order_allowed = AsyncMock(
        return_value=SafetyCheckResult(allowed=True, message="OK")
    )
    adapter = SafetyGateAdapter(mock_gate)
    decision = await adapter.check_order_allowed("user-123")

    assert decision.allowed is True
    assert decision.rejection_code is None


@pytest.mark.asyncio
async def test_adapter_converts_denied_result_with_halt_reason():
    """SafetyCheckResult(allowed=False, halt_reason) → SafetyDecision(rejection_code=halt_reason.value)."""
    from app.safety.adapter import SafetyGateAdapter
    from app.safety.types import HaltReason, SafetyCheckResult

    mock_gate = AsyncMock()
    mock_gate.check_order_allowed = AsyncMock(
        return_value=SafetyCheckResult(
            allowed=False,
            halt_reason=HaltReason.DAILY_LOSS_LIMIT,
            message="일일 손실 한도 도달",
        )
    )
    adapter = SafetyGateAdapter(mock_gate)
    decision = await adapter.check_order_allowed("user-123")

    assert decision.allowed is False
    assert decision.rejection_code == "DAILY_LOSS_LIMIT"
    assert decision.message == "일일 손실 한도 도달"


@pytest.mark.asyncio
async def test_adapter_handles_no_halt_reason():
    """halt_reason=None이면 rejection_code도 None."""
    from app.safety.adapter import SafetyGateAdapter
    from app.safety.types import SafetyCheckResult

    mock_gate = AsyncMock()
    mock_gate.check_order_allowed = AsyncMock(
        return_value=SafetyCheckResult(allowed=False, halt_reason=None, message="blocked")
    )
    adapter = SafetyGateAdapter(mock_gate)
    decision = await adapter.check_order_allowed("user-123")

    assert decision.allowed is False
    assert decision.rejection_code is None
    assert decision.message == "blocked"
