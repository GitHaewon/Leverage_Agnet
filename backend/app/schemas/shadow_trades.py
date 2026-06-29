from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from typing import Any


class ShadowTradeOut(BaseModel):
    id: uuid.UUID
    coin: str
    symbol: str
    direction: str          # LONG | SHORT
    entry_price: Decimal
    tp_price: Decimal
    sl_price: Decimal
    quantity: Decimal
    leverage: int
    status: str             # OPEN | TP_HIT | SL_HIT | CANCELLED
    opened_at: datetime

    exit_price: Decimal | None = None
    pnl_usdt: float | None = None
    duration_seconds: float | None = None
    closed_at: datetime | None = None
    strategy_version: str | None = None
    experiment_label: str | None = None
    signal_id: str | None = None
    position_size_usdt: Decimal | None = None
    margin_usdt: Decimal | None = None
    tp_distance: Decimal | None = None
    sl_distance: Decimal | None = None
    expected_max_loss_usdt: Decimal | None = None
    actual_max_loss_usdt: Decimal | None = None
    risk_budget_usdt: Decimal | None = None
    risk_budget_utilization: Decimal | None = None
    leverage_reason: str | None = None
    reviewer_input_summary: dict[str, Any] | None = None
    reviewer_result: str | None = None
    reviewer_score: float | None = None
    market_regime: str | None = None
    exit_reason: str | None = None
    gross_pnl_usdt: Decimal | None = None
    entry_fee_usdt: Decimal = Decimal("0")
    exit_fee_usdt: Decimal = Decimal("0")
    entry_slippage_usdt: Decimal = Decimal("0")
    exit_slippage_usdt: Decimal = Decimal("0")
    funding_fee_usdt: Decimal = Decimal("0")
    # Compatibility total = entry_slippage_usdt + exit_slippage_usdt.
    estimated_slippage_usdt: Decimal = Decimal("0")
    net_pnl_usdt: Decimal | None = None
    net_return_on_margin_pct: Decimal | None = None
    pnl_calculation_status: str = "UNKNOWN"
    mfe_usdt: Decimal = Decimal("0")
    mae_usdt: Decimal = Decimal("0")
    data_error: bool = False
    system_error: bool = False
    max_hold_seconds: int | None = None
    rejection_code: str | None = None
    rejection_reason: str | None = None

    model_config = {"from_attributes": True}


class ShadowTradeStats(BaseModel):
    total_trades: int
    open_trades: int
    closed_trades: int
    tp_hit: int
    sl_hit: int
    win_rate: float         # 0.0 ~ 100.0
    total_pnl_usdt: float
    avg_pnl_usdt: float
    best_pnl_usdt: float | None
    worst_pnl_usdt: float | None
    avg_duration_minutes: float | None
