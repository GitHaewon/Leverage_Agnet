"""
Live Trading Safety Layer — 거래소 연결 오류 보호.

TRADING_RULES.md §9.1 API_FAILURES 기준.

  - 연속 3회 API 실패 → 30분 자동 중단
  - 30분 경과 후 자동 재개
  - 성공 호출 시 연속 실패 카운터 리셋
  - 중단 중 성공 호출은 카운터를 리셋하지 않음
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import constants
from .state import SafetyStateStore
from .types import AlertLevel, DisconnectState, HaltReason, SafetyCheckResult, SafetyConfig

logger = logging.getLogger(__name__)

NowFn = Callable[[], datetime]


def _default_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ExchangeDisconnectProtection:
    """
    거래소 연결 오류 보호.

    record_api_failure()  — API 실패 기록, 임계값 초과 시 중단
    record_api_success()  — 성공 시 연속 실패 카운터 리셋
    check()               — 현재 연결 오류 중단 상태 확인
    """

    def __init__(
        self,
        store: SafetyStateStore,
        config: SafetyConfig,
        now_fn: NowFn | None = None,
    ) -> None:
        self._store  = store
        self._config = config
        self._now    = now_fn or _default_now

    async def record_api_failure(self) -> SafetyCheckResult:
        """
        API 실패를 기록한다.
        연속 실패가 임계값에 도달하면 중단을 발동한다.
        """
        now   = self._now()
        state = await self._store.get_disconnect_state()

        # 이전 중단이 만료된 경우 리셋
        if state.is_halted and state.halt_until and now >= state.halt_until:
            state = DisconnectState()

        # 중단 중인 경우 카운터 증가 없이 차단 반환
        if state.is_halted:
            remaining = (
                (state.halt_until - now).total_seconds() / 60
                if state.halt_until else 0
            )
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.CONSECUTIVE_API_FAILURES,
                message=f"거래소 연결 오류 중단 중. {remaining:.0f}분 후 자동 재개.",
                alert_level=AlertLevel.CRITICAL,
            )

        state.consecutive_failures += 1
        state.last_failure_at       = now

        if state.consecutive_failures >= self._config.api_failure_halt_threshold:
            state.is_halted  = True
            state.halt_until = now + timedelta(minutes=self._config.api_failure_halt_minutes)
            await self._store.set_disconnect_state(state)
            logger.critical(
                "exchange_disconnect_halt triggered failures=%d halt_until=%s",
                state.consecutive_failures, state.halt_until.isoformat(),
            )
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.CONSECUTIVE_API_FAILURES,
                message=(
                    f"거래소 연결 오류: {state.consecutive_failures}회 연속 실패. "
                    f"{self._config.api_failure_halt_minutes}분 중단. "
                    f"재개: {state.halt_until.strftime('%H:%M UTC')}"
                ),
                alert_level=AlertLevel.CRITICAL,
            )

        await self._store.set_disconnect_state(state)
        return SafetyCheckResult(
            allowed=True,
            message=(
                f"API 실패 {state.consecutive_failures}/"
                f"{self._config.api_failure_halt_threshold}회"
            ),
            alert_level=AlertLevel.WARNING,
        )

    async def record_api_success(self) -> None:
        """
        성공적인 API 호출을 기록한다.
        중단 중이 아닐 때만 연속 실패 카운터를 리셋한다.
        """
        now   = self._now()
        state = await self._store.get_disconnect_state()

        # 중단 만료 시 전체 리셋
        if state.is_halted and state.halt_until and now >= state.halt_until:
            await self._store.set_disconnect_state(DisconnectState())
            return

        # 중단 중 성공은 카운터 미리셋 (중단이 해제되어야 리셋)
        if state.is_halted:
            return

        state.consecutive_failures = 0
        await self._store.set_disconnect_state(state)

    async def check(self) -> SafetyCheckResult:
        """현재 연결 오류 중단 상태를 확인한다. 만료 시 자동 재개."""
        now   = self._now()
        state = await self._store.get_disconnect_state()

        if not state.is_halted:
            return SafetyCheckResult(allowed=True, message="OK")

        if state.halt_until and now >= state.halt_until:
            await self._store.set_disconnect_state(DisconnectState())
            return SafetyCheckResult(allowed=True, message="거래소 연결 오류 자동 복구됨")

        remaining = (
            (state.halt_until - now).total_seconds() / 60 if state.halt_until else 0
        )
        return SafetyCheckResult(
            allowed=False,
            halt_reason=HaltReason.CONSECUTIVE_API_FAILURES,
            message=f"거래소 연결 오류 중단 중. {remaining:.0f}분 후 자동 재개.",
            alert_level=AlertLevel.CRITICAL,
        )
