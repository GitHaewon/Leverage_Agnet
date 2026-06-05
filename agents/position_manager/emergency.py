"""
긴급 청산 규칙 — TRADING_RULES.md §10.

청산가까지의 거리를 계산하여 필요한 액션을 결정한다.
실제 청산 실행은 engine.py의 tick()에서 처리한다.
"""
from __future__ import annotations

from decimal import Decimal

from agents.position_manager.models import (
    LiquidationCheck,
    LIQ_DISTANCE_FULL,
    LIQ_DISTANCE_PARTIAL,
    LIQ_DISTANCE_WARNING_HIGH,
    LIQ_DISTANCE_WARNING_MED,
    PositionState,
)


def check_liquidation_distance(
    position: PositionState,
    current_price: Decimal,
) -> LiquidationCheck:
    """§10.2 청산 거리를 계산하고 §10.1 임계값으로 액션을 결정한다.

    LONG:  distance = (current - liq) / current
    SHORT: distance = (liq - current) / current

    distance ≤ 2% → full_close
    distance ≤ 3% → partial_close (50%)
    distance ≤ 5% → warning
    distance ≤ 10% → warning
    """
    distance = _calc_distance(position, current_price)
    action = _distance_to_action(distance)

    return LiquidationCheck(
        position_id=position.id,
        distance_pct=distance,
        action=action,
        current_price=current_price,
        liquidation_price=position.liquidation_price,
    )


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _calc_distance(position: PositionState, current_price: Decimal) -> float:
    """청산가까지의 거리 비율 (0.0 ~ 1.0, 음수는 이미 청산 수준)."""
    if current_price <= 0:
        return 0.0
    if position.direction == "LONG":
        return float((current_price - position.liquidation_price) / current_price)
    return float((position.liquidation_price - current_price) / current_price)


def _distance_to_action(distance: float) -> str:
    """§10.1 임계값 매핑 (가장 심각한 조건 우선)."""
    if distance <= LIQ_DISTANCE_FULL:
        return "full_close"
    if distance <= LIQ_DISTANCE_PARTIAL:
        return "partial_close"
    if distance <= LIQ_DISTANCE_WARNING_MED:
        return "warning"
    if distance <= LIQ_DISTANCE_WARNING_HIGH:
        return "warning"
    return "none"
