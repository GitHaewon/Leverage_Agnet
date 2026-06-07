"""
Execution Engine 테스트 공통 픽스처 헬퍼.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agents.execution.models import ExecutionRequest, FilledOrder, OrderTicket
from agents.risk.models import (
    AccountState,
    OpenPosition,
    RawSignal,
    UserContext,
    ValidationResult,
)

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ── 입력 헬퍼 ────────────────────────────────────────────────────────────────────

def make_signal(**kwargs: Any) -> RawSignal:
    defaults: dict[str, Any] = dict(
        direction="LONG",
        coin="BTC",
        symbol="BTCUSDT",
        confidence=0.87,
        entry_price=Decimal("67450"),
        take_profit=Decimal("69200"),
        stop_loss=Decimal("66800"),
        leverage=5,
        signal_id=None,
    )
    defaults.update(kwargs)
    return RawSignal(**defaults)


def make_ctx(**kwargs: Any) -> UserContext:
    defaults: dict[str, Any] = dict(
        user_id=_USER_ID,
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
    defaults.update(kwargs)
    return UserContext(**defaults)


def make_account(**kwargs: Any) -> AccountState:
    defaults: dict[str, Any] = dict(
        available_balance=Decimal("10000"),
        total_balance=Decimal("10000"),
        initial_balance=Decimal("10000"),
        open_positions_count=0,
        open_positions_risk_usdt=Decimal("0"),
    )
    defaults.update(kwargs)
    return AccountState(**defaults)


def make_request(**kwargs: Any) -> ExecutionRequest:
    defaults: dict[str, Any] = dict(
        signal=make_signal(),
        user_ctx=make_ctx(),
        account=make_account(),
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("1000"),
        consecutive_losses=0,
        open_positions_count=0,
        same_coin_position=None,
    )
    defaults.update(kwargs)
    return ExecutionRequest(**defaults)


# ── ValidationResult 헬퍼 ─────────────────────────────────────────────────────────

def make_approved_validation(**kwargs: Any) -> ValidationResult:
    defaults: dict[str, Any] = dict(
        approved=True,
        quantity=Decimal("0.001"),
        final_leverage=5,
        margin_required_usdt=Decimal("134.0"),
        max_loss_usdt=Decimal("65.0"),
        max_profit_usdt=Decimal("130.0"),
        rr_ratio=Decimal("2.71"),
        warnings=[],
        pre_action=None,
        existing_position_id=None,
    )
    defaults.update(kwargs)
    return ValidationResult(**defaults)


def make_rejected_validation(code: str = "ORDER_004", reason: str = "R:R 미달") -> ValidationResult:
    return ValidationResult.reject(code, reason)


# ── 테스트용 Stub / Mock ──────────────────────────────────────────────────────────

class StubRiskValidator:
    """
    테스트용 Risk Validator.
    미리 설정된 ValidationResult를 반환 — Redis 의존성 없음.
    """

    def __init__(self, result: ValidationResult) -> None:
        self._result = result
        self.call_count = 0

    async def validate(self, *args: Any, **kwargs: Any) -> ValidationResult:
        self.call_count += 1
        return self._result


class MockGateway:
    """
    테스트용 Order Gateway.
    주문을 recorded_orders에 기록하고 FilledOrder를 반환.
    fail_on_purpose: 특정 purpose에서 예외 발생 (TP/SL 실패 시뮬레이션).
    """

    def __init__(self, fail_on_purpose: str | None = None) -> None:
        self.recorded_orders: list[OrderTicket] = []
        self._counter = 0
        self._fail_on = fail_on_purpose

    async def place_order(self, ticket: OrderTicket) -> FilledOrder:
        if self._fail_on and ticket.purpose == self._fail_on:
            raise RuntimeError(f"Simulated gateway failure on {ticket.purpose}")
        self.recorded_orders.append(ticket)
        self._counter += 1
        return FilledOrder(
            exchange_order_id=f"mock-{self._counter:04d}",
            symbol=ticket.symbol,
            purpose=ticket.purpose,
            side=ticket.side,
            order_type=ticket.order_type,
            quantity=ticket.quantity,
            avg_fill_price=ticket.price,
            fee_usdt=(ticket.quantity * ticket.price * Decimal("0.0004")).quantize(
                Decimal("0.00001")
            ),
            filled_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        )

    async def cancel_all_orders(self, symbol: str) -> int:
        return 0

    @property
    def first(self) -> OrderTicket:
        return self.recorded_orders[0]

    @property
    def second(self) -> OrderTicket:
        return self.recorded_orders[1]

    @property
    def third(self) -> OrderTicket:
        return self.recorded_orders[2]
