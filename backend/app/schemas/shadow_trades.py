from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


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
