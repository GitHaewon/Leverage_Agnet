"""
Alert System 데이터 모델.

순수 Python dataclass — 외부 의존성 없음.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Union


# ── 이벤트 ───────────────────────────────────────────────────────────────────────

@dataclass
class OrderFilledEvent:
    """주문 체결 완료."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    fill_price: Decimal
    quantity: Decimal
    leverage: int
    take_profit: Decimal | None
    stop_loss: Decimal | None
    event_type: str = field(default="order_filled", init=False)


@dataclass
class OrderFailedEvent:
    """주문 실패 (Risk 거부 또는 Gateway 오류)."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    rejection_code: str
    reason: str
    event_type: str = field(default="order_failed", init=False)


@dataclass
class MaxDailyLossEvent:
    """일일 손실 한도 도달 → 자동매매 중단."""
    daily_loss_usdt: Decimal
    limit_usdt: Decimal
    triggered_at: datetime
    event_type: str = field(default="max_daily_loss", init=False)


@dataclass
class KillSwitchEvent:
    """Kill Switch 발동 — 모든 자동매매 즉시 중단."""
    reason: str
    triggered_at: datetime
    event_type: str = field(default="kill_switch", init=False)


@dataclass
class LiquidationRiskEvent:
    """청산가 근접 경고."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    current_price: Decimal
    liq_price: Decimal
    margin_ratio: Decimal    # 0.0 ~ 1.0 (1.0 = 청산)
    event_type: str = field(default="liquidation_risk", init=False)


@dataclass
class EmergencyClosedEvent:
    """TP/SL 설정 실패 → 긴급 시장가 청산 완료."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    exit_price: Decimal       # 긴급 청산 시장가 체결가
    reason: str
    triggered_at: datetime
    event_type: str = field(default="emergency_closed", init=False)


AlertEvent = Union[
    OrderFilledEvent,
    OrderFailedEvent,
    MaxDailyLossEvent,
    KillSwitchEvent,
    LiquidationRiskEvent,
    EmergencyClosedEvent,
]


# ── 결과 ─────────────────────────────────────────────────────────────────────────

@dataclass
class AlertResult:
    """알림 발송 결과."""
    success: bool
    event_type: str
    chat_id: str
    error: str | None = None
