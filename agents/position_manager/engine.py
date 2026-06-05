"""
PositionManagerEngine — 포지션 관리의 단일 진입점.

모든 포지션 작업은 이 클래스를 통해 수행한다.
실제 Binance API 호출 / DB 저장은 이 레이어 밖(서비스 레이어)에서 처리한다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from agents.risk.models import ValidationResult
from agents.position_manager.dca import apply_dca, check_dca_eligibility
from agents.position_manager.emergency import check_liquidation_distance
from agents.position_manager.lifecycle import close_position, open_position, partial_close
from agents.position_manager.models import (
    AccountStats,
    CloseResult,
    DCAEligibility,
    DCAResult,
    LiquidationCheck,
    OpenResult,
    PositionState,
    TAKER_FEE_RATE,
    TickResult,
    TPSLUpdate,
)
from agents.position_manager.tp_sl import (
    check_tp_sl,
    move_sl_to_breakeven,
    update_stop_loss,
    update_take_profit,
    update_tp_and_sl,
)
from agents.risk.models import RawSignal


class PositionManagerEngine:
    """포지션 전체 생명주기 오케스트레이터.

    모든 메서드는 순수 도메인 연산을 수행한다.
    DB 트랜잭션 경계, 이벤트 발행, API 호출은 호출자 책임이다.
    """

    def __init__(self, fee_rate: Decimal = TAKER_FEE_RATE) -> None:
        self._fee_rate = fee_rate

    # ── 오픈 ─────────────────────────────────────────────────────────────────

    def open(
        self,
        user_id: str,
        signal: RawSignal,
        validation: ValidationResult,
    ) -> OpenResult:
        """포지션을 오픈한다."""
        return open_position(user_id, signal, validation, self._fee_rate)

    # ── 청산 ─────────────────────────────────────────────────────────────────

    def close(
        self,
        position: PositionState,
        close_price: Decimal,
        reason: str,
    ) -> CloseResult:
        """포지션 전량 청산."""
        return close_position(position, close_price, reason, self._fee_rate)

    def partial_close(
        self,
        position: PositionState,
        close_price: Decimal,
        ratio: float,
    ) -> CloseResult:
        """포지션 부분 청산."""
        return partial_close(position, close_price, ratio, self._fee_rate)

    # ── DCA ─────────────────────────────────────────────────────────────────

    def check_dca(
        self,
        position: PositionState,
        dca_direction: str,
        dca_entry_price: Decimal,
        dca_risk_usdt: Decimal,
        current_atr: Decimal,
        account: AccountStats,
    ) -> DCAEligibility:
        """DCA 자격 검사 (§8.2). 실행하지 않고 결과만 반환."""
        return check_dca_eligibility(
            position, dca_direction, dca_entry_price, dca_risk_usdt, current_atr, account
        )

    def dca(
        self,
        position: PositionState,
        dca_entry_price: Decimal,
        validation: ValidationResult,
    ) -> DCAResult:
        """DCA 적용 (자격 검사 없이 직접 적용).

        check_dca()로 자격 검사를 먼저 수행한 뒤 호출한다.
        """
        return apply_dca(position, dca_entry_price, validation, self._fee_rate)

    # ── TP / SL 관리 ─────────────────────────────────────────────────────────

    def update_sl(
        self,
        position: PositionState,
        new_sl: Decimal,
        reason: str,
    ) -> TPSLUpdate:
        """SL 수정 (trailing 등)."""
        return update_stop_loss(position, new_sl, reason)

    def update_tp(
        self,
        position: PositionState,
        new_tp: Decimal,
        reason: str,
    ) -> TPSLUpdate:
        """TP 수정."""
        return update_take_profit(position, new_tp, reason)

    def update_tp_sl(
        self,
        position: PositionState,
        new_tp: Optional[Decimal],
        new_sl: Optional[Decimal],
        reason: str,
    ) -> TPSLUpdate:
        """TP와 SL 동시 수정."""
        return update_tp_and_sl(position, new_tp, new_sl, reason)

    def move_to_breakeven(
        self,
        position: PositionState,
        current_price: Decimal,
    ) -> Optional[TPSLUpdate]:
        """SL을 손익분기점으로 이동 (조건 미충족 시 None)."""
        return move_sl_to_breakeven(position, current_price, self._fee_rate)

    # ── 가격 업데이트 (tick) ──────────────────────────────────────────────────

    def tick(
        self,
        position: PositionState,
        current_price: Decimal,
    ) -> TickResult:
        """가격 업데이트를 처리하고 TP/SL 도달 및 긴급 청산 여부를 반환한다.

        TP/SL 도달 시 자동으로 포지션을 청산하고 CloseResult를 채워 반환한다.
        긴급 청산 액션(partial_close/full_close)은 호출자가 직접 수행해야 한다 —
        이 메서드는 liquidation_check에 action만 담아 반환한다.
        """
        position.current_price = current_price

        # 1. TP/SL 체크
        tp_sl_status = check_tp_sl(position, current_price)
        close_result: Optional[CloseResult] = None

        if tp_sl_status == "tp_hit":
            close_result = self.close(position, current_price, "tp_hit")
        elif tp_sl_status == "sl_hit":
            close_result = self.close(position, current_price, "sl_hit")

        # 2. 긴급 청산 거리 체크 (포지션이 아직 열려 있을 때만)
        liq_check: LiquidationCheck
        if position.is_open:
            liq_check = check_liquidation_distance(position, current_price)
        else:
            liq_check = LiquidationCheck(
                position_id=position.id,
                distance_pct=1.0,
                action="none",
                current_price=current_price,
                liquidation_price=position.liquidation_price,
            )

        return TickResult(
            position_id=position.id,
            current_price=current_price,
            tp_sl_status=tp_sl_status,
            close_result=close_result,
            liq_check=liq_check,
        )
