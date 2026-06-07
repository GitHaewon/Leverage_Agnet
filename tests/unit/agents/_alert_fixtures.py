"""
Alert System 테스트 공통 픽스처 헬퍼.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agents.alert.models import (
    KillSwitchEvent,
    LiquidationRiskEvent,
    MaxDailyLossEvent,
    OrderFailedEvent,
    OrderFilledEvent,
)

_NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


def now() -> datetime:
    return _NOW


# ── 이벤트 헬퍼 ──────────────────────────────────────────────────────────────────

def make_order_filled(**kwargs: Any) -> OrderFilledEvent:
    defaults: dict[str, Any] = dict(
        symbol="BTCUSDT",
        direction="LONG",
        fill_price=Decimal("67452.00"),
        quantity=Decimal("0.00741"),
        leverage=5,
        take_profit=Decimal("69200.00"),
        stop_loss=Decimal("66800.00"),
    )
    defaults.update(kwargs)
    return OrderFilledEvent(**defaults)


def make_order_failed(**kwargs: Any) -> OrderFailedEvent:
    defaults: dict[str, Any] = dict(
        symbol="BTCUSDT",
        direction="LONG",
        rejection_code="ORDER_004",
        reason="R:R 2.0 미달",
    )
    defaults.update(kwargs)
    return OrderFailedEvent(**defaults)


def make_max_daily_loss(**kwargs: Any) -> MaxDailyLossEvent:
    defaults: dict[str, Any] = dict(
        daily_loss_usdt=Decimal("245.80"),
        limit_usdt=Decimal("200.00"),
        triggered_at=_NOW,
    )
    defaults.update(kwargs)
    return MaxDailyLossEvent(**defaults)


def make_kill_switch(**kwargs: Any) -> KillSwitchEvent:
    defaults: dict[str, Any] = dict(
        reason="연속 5회 손실",
        triggered_at=_NOW,
    )
    defaults.update(kwargs)
    return KillSwitchEvent(**defaults)


def make_liquidation_risk(**kwargs: Any) -> LiquidationRiskEvent:
    defaults: dict[str, Any] = dict(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("67000.00"),
        current_price=Decimal("61500.00"),
        liq_price=Decimal("60200.00"),
        margin_ratio=Decimal("0.85"),
    )
    defaults.update(kwargs)
    return LiquidationRiskEvent(**defaults)


# ── 테스트용 Sender ───────────────────────────────────────────────────────────────

class CaptureSender:
    """발송 요청을 기록하는 테스트용 Sender."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def send(self, chat_id: str, text: str) -> None:
        self.calls.append({"chat_id": chat_id, "text": text})

    @property
    def last_call(self) -> dict[str, str]:
        return self.calls[-1]

    @property
    def call_count(self) -> int:
        return len(self.calls)


class FailingSender:
    """항상 예외를 발생시키는 테스트용 Sender."""

    def __init__(self, error_msg: str = "Telegram API 오류") -> None:
        self._error_msg = error_msg

    async def send(self, chat_id: str, text: str) -> None:
        raise RuntimeError(self._error_msg)
