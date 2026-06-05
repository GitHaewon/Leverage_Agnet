"""
Position Sizing API 스키마 (Pydantic v2).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SizingRequest(BaseModel):
    """단일 방법 사이징 요청."""
    model_config = ConfigDict(str_strip_whitespace=True)

    method: Literal["fixed_risk", "fixed_dollar", "percent_risk", "kelly"]

    # 시그널 정보
    symbol: Literal["BTCUSDT", "ETHUSDT"]
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal = Field(gt=0)
    stop_loss: Decimal = Field(gt=0, description="필수 — SL 없는 주문 금지")
    take_profit: Decimal | None = Field(None, gt=0)
    leverage: int = Field(ge=1, le=20)

    # 방법별 파라미터
    risk_pct: float | None = Field(None, ge=0.005, le=0.05,
                                    description="fixed_risk / percent_risk 용 (0.005~0.05)")
    risk_usdt: Decimal | None = Field(None, gt=0,
                                       description="fixed_dollar 용 고정 손실 한도 (USDT)")
    kelly_fraction: float = Field(default=0.25, ge=0.1, le=1.0,
                                   description="Kelly 분수 비율 (0.25 = Quarter-Kelly)")

    # 거래 이력 기간 (Kelly용)
    kelly_lookback_days: int = Field(default=90, ge=7, le=365)


class CompareRequest(BaseModel):
    """4가지 방법 비교 요청."""
    model_config = ConfigDict(str_strip_whitespace=True)

    symbol: Literal["BTCUSDT", "ETHUSDT"]
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal = Field(gt=0)
    stop_loss: Decimal = Field(gt=0)
    take_profit: Decimal | None = None
    leverage: int = Field(ge=1, le=20)

    base_risk_pct: float = Field(default=0.02, ge=0.005, le=0.05,
                                  description="Fixed Risk / Percent Risk 기준 비율")
    kelly_fraction: float = Field(default=0.25, ge=0.1, le=1.0)
    kelly_lookback_days: int = Field(default=90, ge=7, le=365)


# ── 응답 스키마 ────────────────────────────────────────────────────────────────

class KellyData(BaseModel):
    full_kelly: float
    applied_fraction: float
    multiplier: float
    win_rate: str
    avg_odds: float
    sample_size: int
    is_valid: bool
    reason: str | None = None


class SizingData(BaseModel):
    method: str
    risk_amount_usdt: str
    risk_pct: str
    quantity: str
    margin_used: str
    position_value: str
    max_loss: str
    max_profit: str
    final_leverage: int
    rr_ratio: str
    kelly: KellyData | None = None
    warnings: list[str] = []


class TradeStatsData(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: str
    avg_win_usdt: str
    avg_loss_usdt: str
    avg_odds: float
    profit_factor: float
    total_pnl: str
    period_days: int


class KellyStatsData(BaseModel):
    trade_stats: TradeStatsData
    kelly_result: KellyData


class CompareData(BaseModel):
    signal: dict
    account_balance: str
    methods: dict[str, SizingData | dict]
