"""
TP / SL 모니터링 및 관리.

포함 기능:
  - TP/SL 도달 여부 체크
  - SL 수정 (trailing, breakeven 이동)
  - TP 수정
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from agents.position_manager.models import (
    PositionState,
    TAKER_FEE_RATE,
    TPSLUpdate,
)


def check_tp_sl(
    position: PositionState,
    current_price: Decimal,
) -> Optional[Literal["tp_hit", "sl_hit"]]:
    """현재가가 TP 또는 SL에 도달했는지 확인한다.

    Returns:
        "tp_hit" | "sl_hit" | None
    """
    if not position.is_open:
        return None

    if position.direction == "LONG":
        if current_price >= position.take_profit:
            return "tp_hit"
        if current_price <= position.stop_loss:
            return "sl_hit"
    else:
        if current_price <= position.take_profit:
            return "tp_hit"
        if current_price >= position.stop_loss:
            return "sl_hit"
    return None


def update_stop_loss(
    position: PositionState,
    new_sl: Decimal,
    reason: str,
) -> TPSLUpdate:
    """SL을 new_sl로 갱신한다.

    LONG: new_sl은 entry_price 아래여야 한다 (또는 breakeven 이동 허용).
    SHORT: new_sl은 entry_price 위여야 한다 (또는 breakeven 이동 허용).
    """
    assert position.is_open, f"청산된 포지션의 SL을 수정할 수 없습니다: {position.id}"

    if position.direction == "LONG" and new_sl >= position.current_price:
        raise ValueError(
            f"LONG SL({new_sl})은 현재가({position.current_price}) 아래여야 합니다"
        )
    if position.direction == "SHORT" and new_sl <= position.current_price:
        raise ValueError(
            f"SHORT SL({new_sl})은 현재가({position.current_price}) 위여야 합니다"
        )

    old_sl = position.stop_loss
    position.stop_loss = new_sl

    return TPSLUpdate(
        position=position,
        field_updated="sl",
        old_tp=None,
        old_sl=old_sl,
        new_tp=None,
        new_sl=new_sl,
        reason=reason,
    )


def update_take_profit(
    position: PositionState,
    new_tp: Decimal,
    reason: str,
) -> TPSLUpdate:
    """TP를 new_tp로 갱신한다."""
    assert position.is_open, f"청산된 포지션의 TP를 수정할 수 없습니다: {position.id}"

    if position.direction == "LONG" and new_tp <= position.current_price:
        raise ValueError(
            f"LONG TP({new_tp})는 현재가({position.current_price}) 위여야 합니다"
        )
    if position.direction == "SHORT" and new_tp >= position.current_price:
        raise ValueError(
            f"SHORT TP({new_tp})는 현재가({position.current_price}) 아래여야 합니다"
        )

    old_tp = position.take_profit
    position.take_profit = new_tp

    return TPSLUpdate(
        position=position,
        field_updated="tp",
        old_tp=old_tp,
        old_sl=None,
        new_tp=new_tp,
        new_sl=None,
        reason=reason,
    )


def move_sl_to_breakeven(
    position: PositionState,
    current_price: Decimal,
    fee_rate: Decimal = TAKER_FEE_RATE,
) -> Optional[TPSLUpdate]:
    """포지션이 충분히 수익권에 있을 때 SL을 손익분기점으로 이동한다.

    손익분기가 현재 SL보다 유리한 경우에만 이동한다.
    Returns None이면 이동 조건 미충족 (호출자는 무시).
    """
    assert position.is_open

    breakeven = _calc_breakeven(position, fee_rate)

    if position.direction == "LONG":
        if current_price <= breakeven:
            return None  # 아직 손익분기 못 넘음
        if position.stop_loss >= breakeven:
            return None  # 이미 손익분기 이상의 SL
        if breakeven >= current_price:
            return None  # 유효하지 않은 breakeven
        new_sl = breakeven
    else:
        if current_price >= breakeven:
            return None
        if position.stop_loss <= breakeven:
            return None
        if breakeven <= current_price:
            return None
        new_sl = breakeven

    old_sl = position.stop_loss
    position.stop_loss = new_sl
    position.current_price = current_price

    return TPSLUpdate(
        position=position,
        field_updated="sl",
        old_tp=None,
        old_sl=old_sl,
        new_tp=None,
        new_sl=new_sl,
        reason="breakeven",
    )


def update_tp_and_sl(
    position: PositionState,
    new_tp: Optional[Decimal],
    new_sl: Optional[Decimal],
    reason: str,
) -> TPSLUpdate:
    """TP와 SL을 동시에 갱신한다. None이면 해당 값 유지."""
    assert position.is_open

    old_tp = position.take_profit
    old_sl = position.stop_loss

    if new_tp is not None:
        position.take_profit = new_tp
    if new_sl is not None:
        position.stop_loss = new_sl

    field = "both" if (new_tp is not None and new_sl is not None) else (
        "tp" if new_tp is not None else "sl"
    )

    return TPSLUpdate(
        position=position,
        field_updated=field,
        old_tp=old_tp,
        old_sl=old_sl,
        new_tp=new_tp,
        new_sl=new_sl,
        reason=reason,
    )


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _calc_breakeven(position: PositionState, fee_rate: Decimal) -> Decimal:
    """양방향 수수료를 포함한 손익분기 가격.

    LONG:  breakeven = entry × (1 + 2 × fee_rate)
    SHORT: breakeven = entry × (1 - 2 × fee_rate)
    """
    if position.direction == "LONG":
        return position.entry_price * (Decimal("1") + Decimal("2") * fee_rate)
    return position.entry_price * (Decimal("1") - Decimal("2") * fee_rate)
