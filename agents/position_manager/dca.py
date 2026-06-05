"""
DCA (Dollar Cost Averaging) — 자격 검사 및 적용.

TRADING_RULES.md §8 전체 준수.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from agents.risk.models import ValidationResult
from agents.position_manager.lifecycle import _calc_liquidation_price
from agents.position_manager.models import (
    AccountStats,
    DCAEligibility,
    DCAResult,
    DCA_DAILY_LOSS_WARNING_PCT,
    DCA_DRAWDOWN_MAX_PCT,
    DCA_MIN_PRICE_MOVE_ATR,
    DCA_RISK_MULTIPLIER,
    DCA_WEEKLY_LOSS_WARNING_PCT,
    MAX_DCA_COUNT,
    PositionState,
    TAKER_FEE_RATE,
)


def check_dca_eligibility(
    position: PositionState,
    dca_direction: str,
    dca_entry_price: Decimal,
    dca_risk_usdt: Decimal,
    current_atr: Decimal,
    account: AccountStats,
) -> DCAEligibility:
    """TRADING_RULES.md §8.2 DCA 허용 조건을 모두 검사한다.

    5개 조건 중 하나라도 불충족 시 DCA 거부.
    """
    # 조건 1: 동일 방향
    if position.direction != dca_direction:
        return DCAEligibility(False, "DCA_DIRECTION: 반대 방향 — DCA 불가")

    # 조건 2: DCA 횟수 한도 (§8.1)
    if position.dca_count >= MAX_DCA_COUNT:
        return DCAEligibility(False, f"DCA_LIMIT: 최대 DCA {MAX_DCA_COUNT}회 초과")

    # 조건 3: 가격 이동 충분성 — 충동 DCA 방지 (§8.2)
    price_move = abs(dca_entry_price - position.entry_price)
    min_move = current_atr * DCA_MIN_PRICE_MOVE_ATR
    if price_move < min_move:
        return DCAEligibility(
            False,
            f"DCA_PREMATURE: 가격 이동 {price_move:.2f} < ATR 기준 {min_move:.2f}",
        )

    # 조건 4: DCA 후 총 리스크가 원래 리스크의 2배 이하 (§8.2)
    current_risk = _estimate_position_risk(position)
    total_risk = current_risk + dca_risk_usdt
    risk_limit = position.original_risk_usdt * DCA_RISK_MULTIPLIER
    if total_risk > risk_limit:
        return DCAEligibility(
            False,
            f"DCA_RISK: DCA 후 총 리스크 {total_risk:.2f}가 원래 리스크의 {DCA_RISK_MULTIPLIER}배 초과",
        )

    # §8.4 DCA 금지 조건들 ─────────────────────────────────────────────────────

    # 금지 1: 일일 손실 경고(50%) 이상
    if account.daily_loss_limit_usdt > 0:
        daily_ratio = account.daily_loss_usdt / account.daily_loss_limit_usdt
        if daily_ratio >= DCA_DAILY_LOSS_WARNING_PCT:
            return DCAEligibility(
                False,
                f"DCA_FORBIDDEN: 일일 손실 {daily_ratio:.0%} ≥ 경고 임계치 {DCA_DAILY_LOSS_WARNING_PCT:.0%}",
            )

    # 금지 2: 연속 손실 쿨다운 중
    if account.in_cooldown:
        return DCAEligibility(False, "DCA_FORBIDDEN: 연속 손실 쿨다운 중")

    # 금지 3: 주간 손실 경고(75%) 이상
    if account.weekly_loss_limit_usdt > 0:
        weekly_ratio = account.weekly_loss_usdt / account.weekly_loss_limit_usdt
        if weekly_ratio >= DCA_WEEKLY_LOSS_WARNING_PCT:
            return DCAEligibility(
                False,
                f"DCA_FORBIDDEN: 주간 손실 {weekly_ratio:.0%} ≥ 경고 임계치 {DCA_WEEKLY_LOSS_WARNING_PCT:.0%}",
            )

    # 금지 4: 포지션 손실이 5% 이상 (drawdown)
    if position.drawdown_pct >= DCA_DRAWDOWN_MAX_PCT:
        return DCAEligibility(
            False,
            f"DCA_FORBIDDEN: 포지션 손실 {position.drawdown_pct:.1%} ≥ {DCA_DRAWDOWN_MAX_PCT:.0%}",
        )

    return DCAEligibility(True, "OK")


def apply_dca(
    position: PositionState,
    dca_signal_entry: Decimal,
    validation: ValidationResult,
    fee_rate: Decimal = TAKER_FEE_RATE,
) -> DCAResult:
    """DCA를 포지션에 적용한다.

    평균 진입가, 수량, 증거금, 청산가를 재계산한다 (§8.3).
    check_dca_eligibility 통과 후 호출해야 한다.
    """
    assert validation.approved, "DCA ValidationResult.approved must be True"

    dca_qty = validation.quantity
    dca_margin = validation.margin_required_usdt

    # §8.3 가중평균 진입가
    new_avg_entry = _recalculate_avg_entry(
        original_qty=position.quantity,
        original_entry=position.entry_price,
        dca_qty=dca_qty,
        dca_entry=dca_signal_entry,
    )

    dca_fee = (dca_qty * dca_signal_entry * fee_rate).quantize(Decimal("0.0001"))
    new_qty = position.quantity + dca_qty
    new_margin = position.margin_used + dca_margin
    new_liq = _calc_liquidation_price(position.direction, new_avg_entry, position.leverage)

    position.entry_price = new_avg_entry
    position.quantity = new_qty
    position.margin_used = new_margin
    position.liquidation_price = new_liq
    position.dca_count += 1

    return DCAResult(
        position=position,
        added_quantity=dca_qty,
        added_margin=dca_margin,
        new_avg_entry=new_avg_entry,
        dca_fee=dca_fee,
    )


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _recalculate_avg_entry(
    original_qty: Decimal,
    original_entry: Decimal,
    dca_qty: Decimal,
    dca_entry: Decimal,
) -> Decimal:
    """§8.3 가중평균 진입가 계산."""
    total_qty = original_qty + dca_qty
    total_value = (original_qty * original_entry) + (dca_qty * dca_entry)
    return (total_value / total_qty).quantize(Decimal("0.01"))


def _estimate_position_risk(position: PositionState) -> Decimal:
    """현재 포지션의 예상 최대 손실 (SL 기준)."""
    if position.direction == "LONG":
        return (position.entry_price - position.stop_loss) * position.quantity
    return (position.stop_loss - position.entry_price) * position.quantity
