"""
Position Manager 테스트 공통 픽스처 헬퍼.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from agents.position_manager.lifecycle import _calc_liquidation_price
from agents.position_manager.models import (
    AccountStats,
    PositionState,
    TAKER_FEE_RATE,
)
from agents.risk.models import RawSignal, ValidationResult


def make_validation(
    *,
    qty: float = 0.01,
    leverage: int = 5,
    margin: float = 200.0,
    max_loss: float = 50.0,
    rr: float = 2.5,
) -> ValidationResult:
    return ValidationResult(
        approved=True,
        quantity=Decimal(str(qty)),
        final_leverage=leverage,
        margin_required_usdt=Decimal(str(margin)),
        max_loss_usdt=Decimal(str(max_loss)),
        max_profit_usdt=Decimal(str(max_loss * rr)),
        rr_ratio=Decimal(str(rr)),
    )


def make_signal(
    *,
    direction: str = "LONG",
    coin: str = "BTC",
    symbol: str = "BTCUSDT",
    entry: float = 67000.0,
    tp: float = 70000.0,
    sl: float = 66000.0,
    leverage: int = 5,
    confidence: float = 0.75,
) -> RawSignal:
    return RawSignal(
        direction=direction,
        coin=coin,
        symbol=symbol,
        confidence=confidence,
        entry_price=Decimal(str(entry)),
        take_profit=Decimal(str(tp)),
        stop_loss=Decimal(str(sl)),
        leverage=leverage,
        signal_id=uuid.uuid4(),
    )


def make_position(
    *,
    direction: str = "LONG",
    entry: float = 67000.0,
    tp: float = 70000.0,
    sl: float = 66000.0,
    qty: float = 0.01,
    leverage: int = 5,
    margin: float = 134.0,
    original_risk: float = 10.0,
    current_price: Optional[float] = None,
    dca_count: int = 0,
    status: str = "open",
    coin: str = "BTC",
    symbol: str = "BTCUSDT",
) -> PositionState:
    entry_d = Decimal(str(entry))
    liq = _calc_liquidation_price(direction, entry_d, leverage)
    return PositionState(
        id=str(uuid.uuid4()),
        user_id="user-001",
        coin=coin,
        symbol=symbol,
        direction=direction,
        status=status,
        entry_price=entry_d,
        take_profit=Decimal(str(tp)),
        stop_loss=Decimal(str(sl)),
        liquidation_price=liq,
        current_price=Decimal(str(current_price)) if current_price else entry_d,
        quantity=Decimal(str(qty)),
        original_quantity=Decimal(str(qty)),
        leverage=leverage,
        margin_used=Decimal(str(margin)),
        original_margin=Decimal(str(margin)),
        original_risk_usdt=Decimal(str(original_risk)),
        realized_pnl=Decimal("0"),
        dca_count=dca_count,
        opened_at=datetime.now(timezone.utc),
    )


def make_account(
    *,
    daily_loss: float = 0.0,
    daily_limit: float = 100.0,
    weekly_loss: float = 0.0,
    weekly_limit: float = 300.0,
    consecutive_losses: int = 0,
    in_cooldown: bool = False,
) -> AccountStats:
    return AccountStats(
        daily_loss_usdt=Decimal(str(daily_loss)),
        daily_loss_limit_usdt=Decimal(str(daily_limit)),
        weekly_loss_usdt=Decimal(str(weekly_loss)),
        weekly_loss_limit_usdt=Decimal(str(weekly_limit)),
        consecutive_losses=consecutive_losses,
        in_cooldown=in_cooldown,
    )
