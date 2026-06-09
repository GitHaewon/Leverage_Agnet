"""
Live Trading Safety Layer — 드로우다운 보호.

고점 대비 일정 비율 이상 하락 시 자동매매를 중단한다.
TRADING_RULES.md §10.4 (계좌 잔고 임계값) 확장 적용.

  - 경고: 고점 대비 10% 하락
  - 중단: 고점 대비 20% 하락 (수동 재활성화 필요)
"""
from __future__ import annotations

import logging

from . import constants
from .state import SafetyStateStore
from .types import AlertLevel, DrawdownState, HaltReason, SafetyCheckResult, SafetyConfig

logger = logging.getLogger(__name__)


class DrawdownProtection:
    """
    계좌 잔고 드로우다운 보호.

    update_balance() — 잔고 갱신 및 고점 추적, 임계값 도달 시 중단
    check()          — 현재 드로우다운 중단 상태 확인
    resume()         — 수동 재활성화 (고점을 현재 잔고로 리셋)
    """

    def __init__(self, store: SafetyStateStore, config: SafetyConfig) -> None:
        self._store  = store
        self._config = config

    async def update_balance(
        self,
        user_id: str,
        current_balance: float,
    ) -> SafetyCheckResult:
        """
        현재 잔고로 상태를 갱신한다.
        고점 갱신 → 드로우다운 계산 → 임계값 비교.
        """
        state = await self._store.get_drawdown_state(user_id)

        # 이미 중단 중이면 잔고만 갱신
        if state.is_halted:
            state.current_balance = current_balance
            await self._store.set_drawdown_state(user_id, state)
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.DRAWDOWN_PROTECTION,
                message=(
                    f"드로우다운 보호 활성 중. "
                    f"고점 ${state.peak_balance:.2f} → 현재 ${current_balance:.2f}. "
                    f"수동 재활성화 필요."
                ),
                alert_level=AlertLevel.CRITICAL,
            )

        # 최초 잔고 또는 고점 갱신
        if state.peak_balance <= 0.0 or current_balance > state.peak_balance:
            state.peak_balance = current_balance
            state.warning_sent = False

        state.current_balance = current_balance

        if state.peak_balance <= 0.0:
            await self._store.set_drawdown_state(user_id, state)
            return SafetyCheckResult(allowed=True, message="OK")

        drawdown_pct = (state.peak_balance - current_balance) / state.peak_balance

        if drawdown_pct >= self._config.drawdown_halt_pct:
            state.is_halted = True
            await self._store.set_drawdown_state(user_id, state)
            logger.critical(
                "drawdown_protection_triggered user=%s drawdown=%.1f%% peak=%.2f current=%.2f",
                user_id, drawdown_pct * 100, state.peak_balance, current_balance,
            )
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.DRAWDOWN_PROTECTION,
                message=(
                    f"드로우다운 보호 발동: {drawdown_pct:.1%} "
                    f"(고점 ${state.peak_balance:.2f} → 현재 ${current_balance:.2f}). "
                    f"수동 재활성화 필요."
                ),
                alert_level=AlertLevel.CRITICAL,
            )

        if drawdown_pct >= self._config.drawdown_warning_pct and not state.warning_sent:
            state.warning_sent = True
            await self._store.set_drawdown_state(user_id, state)
            return SafetyCheckResult(
                allowed=True,
                message=(
                    f"드로우다운 경고: {drawdown_pct:.1%} "
                    f"(중단 임계값: {self._config.drawdown_halt_pct:.0%})"
                ),
                alert_level=AlertLevel.WARNING,
            )

        await self._store.set_drawdown_state(user_id, state)
        return SafetyCheckResult(allowed=True, message="OK")

    async def check(self, user_id: str) -> SafetyCheckResult:
        """현재 드로우다운 중단 상태를 확인한다."""
        state = await self._store.get_drawdown_state(user_id)

        if not state.is_halted:
            return SafetyCheckResult(allowed=True, message="OK")

        return SafetyCheckResult(
            allowed=False,
            halt_reason=HaltReason.DRAWDOWN_PROTECTION,
            message=(
                f"드로우다운 보호 활성: 고점 ${state.peak_balance:.2f}, "
                f"현재 ${state.current_balance:.2f}. 수동 재활성화 필요."
            ),
            alert_level=AlertLevel.CRITICAL,
        )

    async def resume(self, user_id: str) -> None:
        """
        수동 재활성화.
        고점을 현재 잔고로 리셋하여 즉시 재발동 방지.
        """
        state = await self._store.get_drawdown_state(user_id)
        state.is_halted    = False
        state.warning_sent = False
        state.peak_balance = state.current_balance  # 현재 잔고를 새 고점으로
        await self._store.set_drawdown_state(user_id, state)
        logger.info(
            "drawdown_protection_resumed user=%s new_peak=%.2f",
            user_id, state.peak_balance,
        )
