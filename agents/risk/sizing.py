"""
포지션 사이징 계산 — TRADING_RULES.md §7.

핵심 공식:
  sl_distance   = |entry - stop_loss|
  risk_amount   = balance × risk_per_trade
  position_size = risk_amount / sl_distance  (증거금)
  quantity      = (position_size × leverage) / entry_price
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_DOWN

from agents.risk.constants import (
    BINANCE_LOT_SIZES,
    BINANCE_MIN_NOTIONAL,
    MAX_SINGLE_POSITION_MARGIN_RATIO,
    MARGIN_BUFFER_RATIO,
    MIN_RR_RATIO,
    PLAN_MAX_LEVERAGE,
    RISK_PROFILE_DEFAULT_LEVERAGE,
    SYSTEM_MAX_LEVERAGE,
)
from agents.risk.models import PositionSizingResult


# ── 레버리지 결정 (§1.5) ────────────────────────────────────────────────────────

def resolve_final_leverage(
    ai_recommended: int,
    user_max: int,
    plan: str,
    risk_profile: str | None = None,
) -> int:
    """
    4중 상한 중 가장 낮은 값 적용 (TRADING_RULES.md §1.5).
    min(ai_recommended, user_max, plan_max, SYSTEM_MAX)
    """
    plan_max = PLAN_MAX_LEVERAGE.get(plan, 5)
    return min(ai_recommended, user_max, plan_max, SYSTEM_MAX_LEVERAGE)


# ── 수량 반올림 (§7.2) ──────────────────────────────────────────────────────────

def round_to_lot_size(quantity: Decimal, symbol: str) -> Decimal:
    """
    Binance lot size로 내림 처리 (초과 거래 방지).
    항상 floor — ceil은 예상보다 큰 포지션을 만들 수 있음.
    """
    lot = Decimal(str(BINANCE_LOT_SIZES.get(symbol, BINANCE_LOT_SIZES["DEFAULT"])))
    return (quantity / lot).to_integral_value(rounding=ROUND_DOWN) * lot


# ── R:R 비율 검증 (§7.4) ────────────────────────────────────────────────────────

def validate_rr_ratio(
    entry: Decimal,
    take_profit: Decimal | None,
    stop_loss: Decimal,
    direction: str,
) -> tuple[bool, Decimal, str]:
    """
    Returns: (is_valid, rr_ratio, reason)
    """
    if take_profit is None:
        return False, Decimal("0"), "ORDER_004: 목표가(take_profit)가 설정되지 않았습니다"

    if direction == "LONG":
        profit_distance = take_profit - entry
        loss_distance = entry - stop_loss
    else:  # SHORT
        profit_distance = entry - take_profit
        loss_distance = stop_loss - entry

    if loss_distance <= 0:
        return False, Decimal("0"), "ORDER_004: 손절가 방향이 진입가보다 유리한 쪽"

    if profit_distance <= 0:
        return False, Decimal("0"), "ORDER_004: 목표가 방향이 진입가보다 불리한 쪽"

    rr = profit_distance / loss_distance

    if rr < Decimal(str(MIN_RR_RATIO)):
        return False, rr, (
            f"ORDER_004: R:R {rr:.2f} < 최소 {MIN_RR_RATIO} "
            f"(진입 {entry}, TP {take_profit}, SL {stop_loss})"
        )

    return True, rr, "OK"


# ── 포지션 사이징 계산 (§7.1) ────────────────────────────────────────────────────

def calculate_position_size(
    account_balance: Decimal,
    risk_per_trade: float,
    entry_price: Decimal,
    stop_loss_price: Decimal,
    leverage: int,
    take_profit_price: Decimal | None = None,
    symbol: str = "BTCUSDT",
) -> PositionSizingResult:
    """
    핵심 공식 (TRADING_RULES.md §7.1):
      sl_distance  = |entry - stop_loss|            [USD/coin]
      risk_amount  = balance × risk_per_trade       [USD]  ← SL 도달 시 최대 손실
      quantity     = risk_amount / sl_distance      [coin] ← SL에서 risk_amount 손실이 발생하는 수량
      margin_used  = quantity × entry_price / lev   [USD]  ← 필요 증거금
      position_value = quantity × entry_price       [USD]  ← 명목 포지션 가치
    """
    sl_distance = abs(entry_price - stop_loss_price)
    if sl_distance == 0:
        raise ValueError("entry_price와 stop_loss_price가 동일합니다")

    risk_amount = account_balance * Decimal(str(risk_per_trade))
    # quantity: SL 도달 시 정확히 risk_amount만큼 손실이 발생하는 수량
    raw_quantity = risk_amount / sl_distance
    quantity = round_to_lot_size(raw_quantity, symbol)

    # 증거금 및 포지션 가치
    lev = Decimal(str(leverage))
    margin_used = quantity * entry_price / lev
    position_value = quantity * entry_price

    # 실제 최대 손실 (lot_size 반올림으로 risk_amount와 미세하게 다를 수 있음)
    max_loss = quantity * sl_distance

    # R:R 기반 최대 수익 계산
    if take_profit_price is not None:
        if entry_price > stop_loss_price:  # LONG
            tp_distance = take_profit_price - entry_price
        else:  # SHORT
            tp_distance = entry_price - take_profit_price
        max_profit = quantity * tp_distance
    else:
        max_profit = Decimal("0")

    return PositionSizingResult(
        quantity=quantity,
        margin_used=margin_used.quantize(Decimal("0.01")),
        position_value=position_value.quantize(Decimal("0.01")),
        max_loss=max_loss.quantize(Decimal("0.01")),
        max_profit=max_profit.quantize(Decimal("0.01")),
        final_leverage=leverage,
    )


# ── 포지션 사이징 유효성 검증 (§7.3) ─────────────────────────────────────────────

def validate_position_size(
    result: PositionSizingResult,
    available_balance: Decimal,
    entry_price: Decimal,
    symbol: str,
) -> tuple[bool, str]:
    """
    Returns: (is_valid, reason)
    """
    min_qty = Decimal(str(BINANCE_LOT_SIZES.get(symbol, BINANCE_LOT_SIZES["DEFAULT"])))
    min_notional = BINANCE_MIN_NOTIONAL.get(symbol, BINANCE_MIN_NOTIONAL["DEFAULT"])

    # 최소 수량
    if result.quantity < min_qty:
        return False, (
            f"SIZING: 계산된 수량 {result.quantity} < 최소 주문량 {min_qty} ({symbol})"
        )

    # 최소 주문 금액
    notional = result.quantity * entry_price
    if notional < Decimal(str(min_notional)):
        return False, (
            f"SIZING: 주문 금액 ${notional:.2f} < 최소 ${min_notional}"
        )

    # 단일 포지션 증거금 한도 (§3.3)
    max_margin = available_balance * Decimal(str(MAX_SINGLE_POSITION_MARGIN_RATIO))
    if result.margin_used > max_margin:
        return False, (
            f"SIZING: 증거금 ${result.margin_used:.2f} > "
            f"잔고 {MAX_SINGLE_POSITION_MARGIN_RATIO:.0%} 한도 ${max_margin:.2f}"
        )

    # 잔고 충분성 (10% 버퍼 포함)
    required = result.margin_used * Decimal(str(MARGIN_BUFFER_RATIO))
    if required > available_balance:
        return False, (
            f"SIZING: 필요 증거금 ${required:.2f} (버퍼 포함) > 가용 잔고 ${available_balance:.2f}"
        )

    return True, "OK"


# ── 청산 거리 계산 (§10.2) ──────────────────────────────────────────────────────

def calculate_liquidation_distance(
    direction: str,
    current_price: Decimal,
    liquidation_price: Decimal,
) -> Decimal:
    """
    현재가에서 강제청산까지의 거리 비율.
    LONG:  (current - liq) / current
    SHORT: (liq - current) / current
    """
    if current_price == 0:
        return Decimal("0")
    if direction == "LONG":
        return (current_price - liquidation_price) / current_price
    else:
        return (liquidation_price - current_price) / current_price


# ── DCA 평균 진입가 재계산 (§8.3) ───────────────────────────────────────────────

def recalculate_avg_entry(
    original_qty: Decimal,
    original_entry: Decimal,
    dca_qty: Decimal,
    dca_entry: Decimal,
) -> Decimal:
    """가중평균 진입가 계산."""
    total_qty = original_qty + dca_qty
    if total_qty == 0:
        return dca_entry
    total_value = (original_qty * original_entry) + (dca_qty * dca_entry)
    return total_value / total_qty
