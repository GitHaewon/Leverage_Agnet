"""
포지션 생명주기 — 오픈 / 전량 청산 / 부분 청산.

비즈니스 규칙:
  - 손절 없는 포지션 오픈 금지 (§7.4)
  - 수량 / 증거금 / PnL 계산은 모두 Decimal 사용
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from agents.risk.models import RawSignal, ValidationResult
from agents.position_manager.models import (
    AccountStats,
    CloseResult,
    MAINTENANCE_MARGIN_RATE,
    OpenResult,
    PositionState,
    TAKER_FEE_RATE,
)


def open_position(
    user_id: str,
    signal: RawSignal,
    validation: ValidationResult,
    fee_rate: Decimal = TAKER_FEE_RATE,
) -> OpenResult:
    """Risk 검증 통과된 시그널로 PositionState를 생성한다.

    validation.approved is True여야 하며, signal.stop_loss는 필수다.
    """
    assert validation.approved, "ValidationResult.approved must be True"
    assert signal.stop_loss is not None, "SL 없는 포지션 오픈 금지 (§7.4)"
    assert signal.take_profit is not None, "TP 없는 포지션 오픈 금지"

    qty = validation.quantity
    lev = validation.final_leverage
    margin = validation.margin_required_usdt
    entry = signal.entry_price

    entry_fee = (qty * entry * fee_rate).quantize(Decimal("0.0001"))
    liq = _calc_liquidation_price(signal.direction, entry, lev)

    position = PositionState(
        id=str(uuid.uuid4()),
        user_id=user_id,
        coin=signal.coin,
        symbol=signal.symbol,
        direction=signal.direction,
        status="open",
        entry_price=entry,
        take_profit=signal.take_profit,
        stop_loss=signal.stop_loss,
        liquidation_price=liq,
        current_price=entry,
        quantity=qty,
        original_quantity=qty,
        leverage=lev,
        margin_used=margin,
        original_margin=margin,
        original_risk_usdt=validation.max_loss_usdt,
        realized_pnl=Decimal("0"),
        dca_count=0,
        opened_at=datetime.now(timezone.utc),
    )
    return OpenResult(position=position, entry_fee=entry_fee)


def close_position(
    position: PositionState,
    close_price: Decimal,
    reason: str,
    fee_rate: Decimal = TAKER_FEE_RATE,
) -> CloseResult:
    """포지션 전량 청산."""
    assert position.is_open, f"이미 청산된 포지션: {position.id}"

    close_qty = position.quantity
    gross_pnl, exit_fee, net_pnl = _calc_pnl(
        position.direction, position.entry_price, close_price, close_qty, fee_rate
    )
    net_pnl_q = net_pnl.quantize(Decimal("0.01"))
    pnl_pct = (net_pnl_q / position.margin_used * Decimal("100")) if position.margin_used else Decimal("0")

    position.status = "closed"
    position.closed_at = datetime.now(timezone.utc)
    position.close_reason = reason
    position.current_price = close_price
    position.realized_pnl += net_pnl_q

    return CloseResult(
        position=position,
        closed_quantity=close_qty,
        gross_pnl=gross_pnl.quantize(Decimal("0.01")),
        fee=exit_fee.quantize(Decimal("0.0001")),
        net_pnl=net_pnl_q,
        pnl_pct=pnl_pct.quantize(Decimal("0.01")),
        is_partial=False,
        close_reason=reason,
    )


def partial_close(
    position: PositionState,
    close_price: Decimal,
    ratio: float,
    fee_rate: Decimal = TAKER_FEE_RATE,
) -> CloseResult:
    """포지션 부분 청산.

    ratio: (0.0, 1.0) 범위의 비율 (예: 0.5 → 50% 청산).
    """
    assert position.is_open, f"이미 청산된 포지션: {position.id}"
    if not 0.0 < ratio < 1.0:
        raise ValueError(f"partial_close ratio는 (0, 1) 범위여야 합니다: {ratio}")

    close_qty = (position.quantity * Decimal(str(ratio))).quantize(
        Decimal("0.001"), rounding=ROUND_DOWN
    )
    if close_qty <= 0:
        raise ValueError(
            f"계산된 close_qty={close_qty} ≤ 0 (qty={position.quantity}, ratio={ratio})"
        )

    gross_pnl, exit_fee, net_pnl = _calc_pnl(
        position.direction, position.entry_price, close_price, close_qty, fee_rate
    )
    net_pnl_q = net_pnl.quantize(Decimal("0.01"))
    close_margin = (position.margin_used * Decimal(str(ratio))).quantize(Decimal("0.0001"))
    pnl_pct = (net_pnl_q / close_margin * Decimal("100")) if close_margin else Decimal("0")

    position.quantity -= close_qty
    position.margin_used -= close_margin
    position.realized_pnl += net_pnl_q
    position.status = "partially_closed"
    position.current_price = close_price

    return CloseResult(
        position=position,
        closed_quantity=close_qty,
        gross_pnl=gross_pnl.quantize(Decimal("0.01")),
        fee=exit_fee.quantize(Decimal("0.0001")),
        net_pnl=net_pnl_q,
        pnl_pct=pnl_pct.quantize(Decimal("0.01")),
        is_partial=True,
        close_reason="partial",
    )


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _calc_pnl(
    direction: str,
    entry: Decimal,
    close: Decimal,
    qty: Decimal,
    fee_rate: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """(gross_pnl, exit_fee, net_pnl) 반환."""
    if direction == "LONG":
        gross = (close - entry) * qty
    else:
        gross = (entry - close) * qty
    exit_fee = qty * close * fee_rate
    return gross, exit_fee, gross - exit_fee


def _calc_liquidation_price(direction: str, entry: Decimal, leverage: int) -> Decimal:
    """Binance Isolated Margin 청산가 근사 계산."""
    lev = Decimal(str(leverage))
    if direction == "LONG":
        return entry * (1 - (Decimal("1") / lev) + MAINTENANCE_MARGIN_RATE)
    return entry * (1 + (Decimal("1") / lev) - MAINTENANCE_MARGIN_RATE)
