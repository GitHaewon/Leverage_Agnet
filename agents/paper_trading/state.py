"""
PaperAccountState — in-memory 계좌 상태.

Redis/DB 없이 daily_loss, weekly_loss, consecutive_losses, halt/cooldown을
모두 메모리에서 계산한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from agents.paper_trading.models import PaperPosition, PaperTradeRecord


@dataclass
class PaperAccountState:
    """
    Paper trading 세션의 전체 계좌 상태.

    잔고 모델:
      _balance       = 총 잔고 (포지션 증거금 포함)
      available      = _balance - sum(open_position.margin_used)
      포지션 오픈 시 → _balance -= entry_fee (수수료만 즉시 차감)
      포지션 청산 시 → _balance += net_pnl   (PnL 정산, margin은 available로 복귀)
    """

    user_id: str
    _balance: Decimal
    initial_balance: Decimal
    open_positions: dict[str, PaperPosition] = field(default_factory=dict)
    trade_history: list[PaperTradeRecord] = field(default_factory=list)

    # Halt / Cooldown (in-memory, Redis 대체)
    is_halted: bool = False
    halt_reason: Optional[str] = None
    cooldown_until: Optional[datetime] = None

    # 주간 손실 계산 기준 (세션 시작 시 고정)
    _week_start_balance: Decimal = field(init=False)
    _week_start: date = field(init=False)
    _day_start: date = field(init=False)

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc)
        self._week_start = self._get_week_start(now.date())
        self._day_start = now.date()
        self._week_start_balance = self._balance

    # ── 잔고 접근 ─────────────────────────────────────────────────────────────

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def available_balance(self) -> Decimal:
        locked = sum(p.margin_used for p in self.open_positions.values())
        return max(Decimal("0"), self._balance - locked)

    @property
    def locked_margin(self) -> Decimal:
        return sum(p.margin_used for p in self.open_positions.values())

    def debit_fee(self, fee: Decimal) -> None:
        self._balance -= fee

    def credit_pnl(self, net_pnl: Decimal) -> None:
        self._balance += net_pnl

    # ── 손실 추적 ─────────────────────────────────────────────────────────────

    @property
    def daily_loss_usdt(self) -> Decimal:
        today = datetime.now(timezone.utc).date()
        return sum(
            abs(t.net_pnl)
            for t in self.trade_history
            if t.net_pnl < 0 and t.closed_at.date() == today
        )

    @property
    def weekly_loss_usdt(self) -> Decimal:
        week_start = self._get_week_start(datetime.now(timezone.utc).date())
        return sum(
            abs(t.net_pnl)
            for t in self.trade_history
            if t.net_pnl < 0 and t.closed_at.date() >= week_start
        )

    @property
    def consecutive_losses(self) -> int:
        count = 0
        for trade in reversed(self.trade_history):
            if trade.net_pnl < 0:
                count += 1
            else:
                break
        return count

    @property
    def open_positions_risk_usdt(self) -> Decimal:
        return sum(p.max_loss_usdt for p in self.open_positions.values())

    @property
    def open_positions_count(self) -> int:
        return len(self.open_positions)

    # ── Halt / Cooldown 관리 ──────────────────────────────────────────────────

    def halt(self, reason: str) -> None:
        self.is_halted = True
        self.halt_reason = reason

    def resume(self) -> None:
        self.is_halted = False
        self.halt_reason = None
        self.cooldown_until = None

    def set_cooldown(self, minutes: int) -> None:
        self.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    @property
    def in_cooldown(self) -> bool:
        if self.cooldown_until is None:
            return False
        return datetime.now(timezone.utc) < self.cooldown_until

    # ── 포지션 / 이력 관리 ───────────────────────────────────────────────────

    def add_position(self, position: PaperPosition) -> None:
        self.open_positions[position.id] = position

    def remove_position(self, position_id: str) -> Optional[PaperPosition]:
        return self.open_positions.pop(position_id, None)

    def get_position(self, position_id: str) -> Optional[PaperPosition]:
        return self.open_positions.get(position_id)

    def get_open_by_coin(self, coin: str) -> Optional[PaperPosition]:
        for p in self.open_positions.values():
            if p.coin == coin:
                return p
        return None

    def add_trade(self, record: PaperTradeRecord) -> None:
        self.trade_history.append(record)

    # ── 요약 ─────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        total_trades = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t.net_pnl > 0)
        total_pnl = sum(t.net_pnl for t in self.trade_history)

        return {
            "balance": float(self._balance),
            "initial_balance": float(self.initial_balance),
            "available_balance": float(self.available_balance),
            "locked_margin": float(self.locked_margin),
            "total_pnl": float(total_pnl),
            "total_pnl_pct": float(total_pnl / self.initial_balance * 100) if self.initial_balance else 0,
            "open_positions": self.open_positions_count,
            "total_trades": total_trades,
            "win_rate": wins / total_trades if total_trades else 0,
            "daily_loss_usdt": float(self.daily_loss_usdt),
            "weekly_loss_usdt": float(self.weekly_loss_usdt),
            "consecutive_losses": self.consecutive_losses,
            "is_halted": self.is_halted,
            "in_cooldown": self.in_cooldown,
        }

    # ── 내부 유틸 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _get_week_start(d: date) -> date:
        return d - timedelta(days=d.weekday())
