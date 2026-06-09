"""
Live Trading Safety Layer — 긴급 중단.

TRADING_RULES.md §9.1 SYSTEM_ERROR, LIQUIDATION_EVENT 기준.

긴급 중단 특성:
  - 즉각 발동 (지연 없음)
  - 수동 재활성화만 가능 (자동 해제 없음)
  - 시스템 또는 사용자가 발동 가능
  - 발동 사유와 시각을 반드시 기록
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from .state import SafetyStateStore
from .types import AlertLevel, EmergencyState, HaltReason, SafetyCheckResult

logger = logging.getLogger(__name__)

NowFn = Callable[[], datetime]


def _default_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class EmergencyShutdown:
    """
    긴급 중단 제어.

    activate()    — 긴급 중단 발동 (즉각 효과)
    check()       — 현재 긴급 중단 상태 확인
    deactivate()  — 수동 해제 (명시적 확인 필요)
    is_active()   — 활성 여부 단순 조회
    """

    def __init__(
        self,
        store: SafetyStateStore,
        now_fn: NowFn | None = None,
    ) -> None:
        self._store = store
        self._now   = now_fn or _default_now

    async def activate(
        self,
        reason: str,
        activated_by: str = "system",   # "user" | "system"
    ) -> None:
        """
        긴급 중단을 발동한다.
        수동 재활성화 전까지 모든 신규 주문이 차단된다.
        """
        state = EmergencyState(
            is_active=True,
            activated_at=self._now(),
            activated_by=activated_by,
            reason=reason,
            requires_manual_resume=True,
        )
        await self._store.set_emergency_state(state)
        logger.critical(
            "emergency_shutdown_activated by=%s reason=%s", activated_by, reason
        )

    async def check(self) -> SafetyCheckResult:
        """긴급 중단이 활성 중이면 차단 결과를 반환한다."""
        state = await self._store.get_emergency_state()

        if not state.is_active:
            return SafetyCheckResult(allowed=True, message="OK")

        activated_at_str = (
            state.activated_at.strftime("%Y-%m-%d %H:%M UTC")
            if state.activated_at else "N/A"
        )
        return SafetyCheckResult(
            allowed=False,
            halt_reason=HaltReason.EMERGENCY_SHUTDOWN,
            message=(
                f"긴급 중단 활성: {state.reason} "
                f"(발동: {state.activated_by}, {activated_at_str}). "
                f"수동 재활성화 필요."
            ),
            alert_level=AlertLevel.CRITICAL,
        )

    async def deactivate(self) -> None:
        """
        긴급 중단을 수동으로 해제한다.
        호출자는 사용자 확인 절차를 선행해야 한다.
        """
        await self._store.set_emergency_state(EmergencyState(is_active=False))
        logger.info("emergency_shutdown_deactivated")

    async def is_active(self) -> bool:
        """긴급 중단 활성 여부를 반환한다."""
        state = await self._store.get_emergency_state()
        return state.is_active
