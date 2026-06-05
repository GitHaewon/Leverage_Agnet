"""
Position Manager 데이터 모델.

순수 Python dataclass — 외부 의존성 없음.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

# ── 상수 ─────────────────────────────────────────────────────────────────────

TAKER_FEE_RATE: Decimal = Decimal("0.0004")
MAINTENANCE_MARGIN_RATE: Decimal = Decimal("0.004")

MAX_DCA_COUNT: int = 2
DCA_RISK_MULTIPLIER: Decimal = Decimal("2.0")
DCA_MIN_PRICE_MOVE_ATR: Decimal = Decimal("1.0")

# §8.4 DCA 금지 임계값
DCA_DAILY_LOSS_WARNING_PCT: Decimal = Decimal("0.50")
DCA_WEEKLY_LOSS_WARNING_PCT: Decimal = Decimal("0.75")
DCA_DRAWDOWN_MAX_PCT: float = 0.05

# §10.1 긴급 청산 거리 임계값
LIQ_DISTANCE_WARNING_HIGH: float = 0.10
LIQ_DISTANCE_WARNING_MED: float = 0.05
LIQ_DISTANCE_PARTIAL: float = 0.03
LIQ_DISTANCE_FULL: float = 0.02


# ── 포지션 상태 ───────────────────────────────────────────────────────────────

@dataclass
class PositionState:
    """포지션의 현재 상태 스냅샷.

    entry_price는 DCA 적용 시 가중평균으로 갱신된다.
    """
    id: str
    user_id: str
    coin: str
    symbol: str
    direction: Literal["LONG", "SHORT"]
    status: Literal["open", "partially_closed", "closed"]

    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    liquidation_price: Decimal
    current_price: Decimal

    quantity: Decimal            # 현재 잔여 수량
    original_quantity: Decimal   # 최초 진입 수량
    leverage: int
    margin_used: Decimal         # 현재 잔여 증거금
    original_margin: Decimal     # 최초 증거금
    original_risk_usdt: Decimal  # 최초 예상 최대 손실 (DCA §8.2 조건 4)

    realized_pnl: Decimal        # 부분 청산 누적 실현 PnL
    dca_count: int

    opened_at: datetime
    closed_at: Optional[datetime] = None
    close_reason: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.status in ("open", "partially_closed")

    @property
    def unrealized_pnl(self) -> Decimal:
        """현재가 기준 미실현 PnL (USDT). current_price가 최신이어야 함."""
        if not self.is_open:
            return Decimal("0")
        if self.direction == "LONG":
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @property
    def drawdown_pct(self) -> float:
        """포지션 손실 비율 (original_margin 대비, 양수 = 손실). §8.4 체크용."""
        if self.original_margin <= 0:
            return 0.0
        upnl = self.unrealized_pnl
        if upnl >= 0:
            return 0.0
        return float(abs(upnl) / self.original_margin)


# ── 연산 결과 타입 ─────────────────────────────────────────────────────────────

@dataclass
class OpenResult:
    position: PositionState
    entry_fee: Decimal           # 진입 수수료 (USDT)


@dataclass
class CloseResult:
    position: PositionState
    closed_quantity: Decimal
    gross_pnl: Decimal           # 수수료 제외 PnL
    fee: Decimal                 # 진출 수수료 (entry fee 제외)
    net_pnl: Decimal             # 실질 PnL
    pnl_pct: Decimal             # 증거금 대비 수익률 (%)
    is_partial: bool
    close_reason: str


@dataclass
class DCAEligibility:
    eligible: bool
    reason: str                  # "OK" 또는 거부 코드 (예: "DCA_LIMIT")


@dataclass
class DCAResult:
    position: PositionState      # DCA 적용 후 갱신된 포지션
    added_quantity: Decimal
    added_margin: Decimal
    new_avg_entry: Decimal
    dca_fee: Decimal


@dataclass
class TPSLUpdate:
    position: PositionState
    field_updated: Literal["tp", "sl", "both"]
    old_tp: Optional[Decimal]
    old_sl: Optional[Decimal]
    new_tp: Optional[Decimal]
    new_sl: Optional[Decimal]
    reason: str


@dataclass
class LiquidationCheck:
    """§10.1 청산 거리 체크 결과."""
    position_id: str
    distance_pct: float
    action: Literal["none", "warning", "partial_close", "full_close"]
    current_price: Decimal
    liquidation_price: Decimal


@dataclass
class TickResult:
    """단일 가격 업데이트 처리 결과."""
    position_id: str
    current_price: Decimal
    tp_sl_status: Optional[Literal["tp_hit", "sl_hit"]]
    close_result: Optional[CloseResult]   # tp/sl 도달 시 채워짐
    liq_check: LiquidationCheck


@dataclass
class AccountStats:
    """DCA 자격 검사에 필요한 계좌 상태 (최소 인터페이스)."""
    daily_loss_usdt: Decimal
    daily_loss_limit_usdt: Decimal
    weekly_loss_usdt: Decimal
    weekly_loss_limit_usdt: Decimal
    consecutive_losses: int
    in_cooldown: bool
