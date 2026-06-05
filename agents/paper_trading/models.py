"""
Paper Trading 전용 데이터 모델.

외부 의존성 없는 순수 Python dataclass.
기존 agents/risk/models.py의 RawSignal을 그대로 입력으로 받는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

# Binance Futures taker fee (기본값: 0.04%)
TAKER_FEE_RATE: Decimal = Decimal("0.0004")

# 유지증거금률 (청산가 계산용 — 약 0.4%)
MAINTENANCE_MARGIN_RATE: Decimal = Decimal("0.004")


@dataclass
class PaperUserSettings:
    """Paper trading 세션 설정. 실제 UserSettings/UserContext와 1:1 대응."""

    user_id: str
    plan: Literal["free", "pro", "elite"] = "pro"
    risk_profile: Literal["conservative", "moderate", "aggressive"] = "moderate"
    risk_per_trade: float = 0.02            # 거래당 리스크 2%
    max_leverage: int = 10
    max_concurrent_positions: int = 5
    daily_loss_limit_pct: float = 0.03      # 3%
    weekly_loss_limit_pct: float = 0.10     # 10%
    allowed_hours_start: Optional[str] = None  # "HH:MM" UTC, None = 24시간
    allowed_hours_end: Optional[str] = None
    taker_fee_rate: Decimal = field(default_factory=lambda: TAKER_FEE_RATE)
    is_trading_active: bool = True


@dataclass
class PaperPosition:
    """진행 중 또는 완료된 Paper 포지션."""

    id: str                               # UUID string
    user_id: str
    coin: str                             # "BTC" | "ETH"
    symbol: str                           # "BTCUSDT" | "ETHUSDT"
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    quantity: Decimal                     # 코인 수량 (남은 수량, partial close 시 감소)
    original_quantity: Decimal            # 최초 진입 수량 (불변)
    leverage: int
    take_profit: Decimal
    stop_loss: Decimal
    liquidation_price: Decimal
    margin_used: Decimal                  # 현재 남아있는 증거금
    original_margin: Decimal              # 최초 증거금 (불변)
    max_loss_usdt: Decimal                # 최대 손실 (risk_amount)
    max_profit_usdt: Decimal              # 최대 수익
    original_risk_usdt: Decimal           # DCA 체크용 원래 리스크
    status: Literal["open", "closed", "partially_closed"] = "open"
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))  # 부분 청산 누적 PnL
    current_price: Decimal = field(default_factory=lambda: Decimal("0"))
    dca_count: int = 0
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    close_reason: Optional[str] = None    # "tp_hit"|"sl_hit"|"manual"|"emergency"

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.status == "closed" or self.current_price == 0:
            return Decimal("0")
        if self.direction == "LONG":
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @property
    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def pnl_pct(self) -> Decimal:
        if self.original_margin == 0:
            return Decimal("0")
        return (self.total_pnl / self.original_margin) * 100

    @property
    def is_open(self) -> bool:
        return self.status in ("open", "partially_closed")


@dataclass
class PaperTradeRecord:
    """
    청산된(또는 부분 청산된) 거래 기록.
    tests/unit/agents/test_kill_switch.py의 TradeRecord와 동일 구조.
    """

    id: str
    position_id: str
    user_id: str
    coin: str
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    close_price: Decimal
    quantity: Decimal                     # 이 거래에서 청산된 수량
    leverage: int
    gross_pnl: Decimal                    # 수수료 전 PnL
    fee: Decimal                          # 총 수수료 (진입분 + 청산분)
    net_pnl: Decimal                      # 수수료 후 순 PnL
    pnl_pct: Decimal                      # 증거금 대비 수익률 (%)
    duration_seconds: int
    close_reason: str                     # "tp_hit"|"sl_hit"|"manual"|"partial"|"emergency"
    is_partial: bool = False              # 부분 청산 여부
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SubmitSignalResult:
    """submit_signal() 반환값."""

    accepted: bool
    position: Optional[PaperPosition] = None
    rejection_reason: Optional[str] = None
    rejection_code: Optional[str] = None
    pre_action: Optional[str] = None      # "close_existing" | "dca"
    warnings: list[str] = field(default_factory=list)
    closed_trade: Optional[PaperTradeRecord] = None  # pre_action="close_existing" 시 이전 포지션 청산 기록
