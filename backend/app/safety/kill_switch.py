"""
Live Trading Safety Layer — 일일/주간 킬스위치.

TRADING_RULES.md §4 (일일 손실), §5 (주간 손실) 기준.

킬스위치 발동 조건:
  - 일일: 오늘 확정 손실 >= 일일 한도 → 자정 UTC까지 중단
  - 주간: 이번 주 확정 손실 >= 주간 한도 → 다음 월요일 00:00 UTC까지 중단
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import constants
from .state import SafetyStateStore
from .types import AlertLevel, HaltReason, KillSwitchState, SafetyCheckResult, SafetyConfig

logger = logging.getLogger(__name__)

NowFn = Callable[[], datetime]


def _default_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _next_midnight_utc(now: datetime) -> datetime:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=1)


def _next_monday_utc(now: datetime) -> datetime:
    days_since_monday = now.weekday()
    monday = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday + timedelta(weeks=1)


class DailyKillSwitch:
    """
    일일 손실 킬스위치.

    record_loss()  — 거래 종료 후 손실 누적 + 임계값 체크
    check()        — 주문 실행 전 현재 중단 여부 확인 (자동 리셋 포함)
    reset()        — 관리자 수동 리셋
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

    async def record_loss(
        self,
        user_id: str,
        loss_usdt: float,         # 양수 = 손실 금액
        period_start_balance: float,
    ) -> SafetyCheckResult:
        """손실을 기록하고 일일 한도 초과 시 킬스위치를 발동한다."""
        now   = self._now()
        state = await self._store.get_daily_kill_switch(user_id)

        # 이미 중단 중이면 손실 누적 없이 차단
        if state.is_halted and (state.halt_until is None or now < state.halt_until):
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.DAILY_LOSS_LIMIT,
                message=f"일일 킬스위치 활성 중 (추가 손실 기록 스킵)",
                alert_level=AlertLevel.CRITICAL,
            )

        # 한도 만료 시 자동 리셋
        if state.is_halted and state.halt_until and now >= state.halt_until:
            state = KillSwitchState(user_id=user_id)

        state.period_start_balance = period_start_balance
        state.current_loss_usdt   += loss_usdt

        limit_usdt = period_start_balance * self._config.daily_loss_limit_pct
        loss_ratio = state.current_loss_usdt / limit_usdt if limit_usdt > 0 else 0.0

        if loss_ratio >= constants.DAILY_LOSS_HALT_PCT:
            state.is_halted   = True
            state.halt_reason = HaltReason.DAILY_LOSS_LIMIT
            state.halt_until  = _next_midnight_utc(now)
            await self._store.set_daily_kill_switch(user_id, state)
            logger.critical(
                "daily_kill_switch_triggered user=%s loss=%.2f limit=%.2f",
                user_id, state.current_loss_usdt, limit_usdt,
            )
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.DAILY_LOSS_LIMIT,
                message=(
                    f"일일 손실 한도 도달: ${state.current_loss_usdt:.2f} / ${limit_usdt:.2f} "
                    f"({loss_ratio:.0%}). {state.halt_until.strftime('%H:%M UTC')}까지 중단."
                ),
                alert_level=AlertLevel.CRITICAL,
            )

        await self._store.set_daily_kill_switch(user_id, state)

        if loss_ratio >= constants.DAILY_LOSS_CAUTION_PCT:
            return SafetyCheckResult(
                allowed=True,
                message=f"일일 손실 주의: 한도의 {loss_ratio:.0%} 도달",
                alert_level=AlertLevel.WARNING,
            )
        if loss_ratio >= constants.DAILY_LOSS_WARNING_PCT:
            return SafetyCheckResult(
                allowed=True,
                message=f"일일 손실 경고: 한도의 {loss_ratio:.0%} 도달",
                alert_level=AlertLevel.WARNING,
            )
        return SafetyCheckResult(allowed=True, message="OK")

    async def check(self, user_id: str) -> SafetyCheckResult:
        """현재 일일 킬스위치 상태를 확인한다. 자정이 지나면 자동 리셋."""
        now   = self._now()
        state = await self._store.get_daily_kill_switch(user_id)

        if not state.is_halted:
            return SafetyCheckResult(allowed=True, message="OK")

        if state.halt_until and now >= state.halt_until:
            await self._store.set_daily_kill_switch(user_id, KillSwitchState(user_id=user_id))
            return SafetyCheckResult(allowed=True, message="일일 손실 한도 자동 리셋됨")

        reset_at = state.halt_until.strftime("%Y-%m-%d %H:%M UTC") if state.halt_until else "N/A"
        return SafetyCheckResult(
            allowed=False,
            halt_reason=HaltReason.DAILY_LOSS_LIMIT,
            message=f"일일 손실 한도 중단 중. 리셋: {reset_at}",
            alert_level=AlertLevel.CRITICAL,
        )

    async def reset(self, user_id: str) -> None:
        """관리자 수동 리셋."""
        await self._store.set_daily_kill_switch(user_id, KillSwitchState(user_id=user_id))
        logger.info("daily_kill_switch_reset user=%s", user_id)


class WeeklyKillSwitch:
    """
    주간 손실 킬스위치.

    record_loss()  — 거래 종료 후 손실 누적 + 임계값 체크
    check()        — 주문 실행 전 현재 중단 여부 확인 (월요일 자동 리셋 포함)
    reset()        — 관리자 수동 리셋
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

    async def record_loss(
        self,
        user_id: str,
        loss_usdt: float,
        week_start_balance: float,
    ) -> SafetyCheckResult:
        """손실을 기록하고 주간 한도 초과 시 킬스위치를 발동한다."""
        now   = self._now()
        state = await self._store.get_weekly_kill_switch(user_id)

        if state.is_halted and (state.halt_until is None or now < state.halt_until):
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.WEEKLY_LOSS_LIMIT,
                message="주간 킬스위치 활성 중 (추가 손실 기록 스킵)",
                alert_level=AlertLevel.CRITICAL,
            )

        if state.is_halted and state.halt_until and now >= state.halt_until:
            state = KillSwitchState(user_id=user_id)

        state.period_start_balance = week_start_balance
        state.current_loss_usdt   += loss_usdt

        limit_usdt = week_start_balance * self._config.weekly_loss_limit_pct
        loss_ratio = state.current_loss_usdt / limit_usdt if limit_usdt > 0 else 0.0

        if loss_ratio >= constants.WEEKLY_LOSS_HALT_PCT:
            state.is_halted   = True
            state.halt_reason = HaltReason.WEEKLY_LOSS_LIMIT
            state.halt_until  = _next_monday_utc(now)
            await self._store.set_weekly_kill_switch(user_id, state)
            logger.critical(
                "weekly_kill_switch_triggered user=%s loss=%.2f limit=%.2f",
                user_id, state.current_loss_usdt, limit_usdt,
            )
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.WEEKLY_LOSS_LIMIT,
                message=(
                    f"주간 손실 한도 도달: ${state.current_loss_usdt:.2f} / ${limit_usdt:.2f} "
                    f"({loss_ratio:.0%}). 다음 월요일 00:00 UTC까지 중단."
                ),
                alert_level=AlertLevel.CRITICAL,
            )

        await self._store.set_weekly_kill_switch(user_id, state)

        if loss_ratio >= constants.WEEKLY_LOSS_CAUTION_PCT:
            return SafetyCheckResult(
                allowed=True,
                message=f"주간 손실 주의: 한도의 {loss_ratio:.0%} 도달",
                alert_level=AlertLevel.WARNING,
            )
        if loss_ratio >= constants.WEEKLY_LOSS_WARNING_PCT:
            return SafetyCheckResult(
                allowed=True,
                message=f"주간 손실 경고: 한도의 {loss_ratio:.0%} 도달",
                alert_level=AlertLevel.WARNING,
            )
        return SafetyCheckResult(allowed=True, message="OK")

    async def check(self, user_id: str) -> SafetyCheckResult:
        """현재 주간 킬스위치 상태를 확인한다. 월요일이 지나면 자동 리셋."""
        now   = self._now()
        state = await self._store.get_weekly_kill_switch(user_id)

        if not state.is_halted:
            return SafetyCheckResult(allowed=True, message="OK")

        if state.halt_until and now >= state.halt_until:
            await self._store.set_weekly_kill_switch(user_id, KillSwitchState(user_id=user_id))
            return SafetyCheckResult(allowed=True, message="주간 손실 한도 자동 리셋됨 (월요일)")

        reset_at = state.halt_until.strftime("%Y-%m-%d %H:%M UTC") if state.halt_until else "N/A"
        return SafetyCheckResult(
            allowed=False,
            halt_reason=HaltReason.WEEKLY_LOSS_LIMIT,
            message=f"주간 손실 한도 중단 중. 리셋: {reset_at}",
            alert_level=AlertLevel.CRITICAL,
        )

    async def reset(self, user_id: str) -> None:
        """관리자 수동 리셋."""
        await self._store.set_weekly_kill_switch(user_id, KillSwitchState(user_id=user_id))
        logger.info("weekly_kill_switch_reset user=%s", user_id)
