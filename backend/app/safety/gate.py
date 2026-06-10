"""
Live Trading Safety Layer — 메인 Safety Gate.

모든 주문은 이 Gate를 반드시 통과해야 한다.
Risk Agent 승인 이후 거래소 주문 실행 직전에 호출한다.

검증 순서 (첫 번째 실패에서 단락):
  1. LIVE_TRADING_ENABLED 마스터 스위치
  2. 긴급 중단 (전역)
  3. 거래소 연결 오류 보호 (전역)
  4. 일일 손실 킬스위치 (사용자별)
  5. 주간 손실 킬스위치 (사용자별)
  6. 드로우다운 보호 (사용자별)

Risk Layer 우회 불가 — 이 Gate는 건너뛸 수 없다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from app.observability import metrics as obs

from .disconnect import ExchangeDisconnectProtection
from .drawdown import DrawdownProtection
from .emergency import EmergencyShutdown
from .kill_switch import DailyKillSwitch, WeeklyKillSwitch
from .state import SafetyStateStore
from .types import AlertLevel, HaltReason, SafetyCheckResult, SafetyConfig, UserHaltStatus

logger = logging.getLogger(__name__)

NowFn = Callable[[], datetime]


class SafetyGate:
    """
    Live Trading Safety Gate.

    check_order_allowed()  — 주문 허용 여부 확인 (주문 실행 직전 호출)
    on_trade_closed()      — 거래 종료 후 손실/잔고 상태 업데이트
    on_api_failure()       — API 실패 기록
    on_api_success()       — API 성공 기록
    trigger_emergency()    — 긴급 중단 발동
    deactivate_emergency() — 긴급 중단 수동 해제
    resume_drawdown()      — 드로우다운 보호 수동 재활성화
    reset_daily_switch()   — 일일 킬스위치 수동 리셋 (관리자)
    reset_weekly_switch()  — 주간 킬스위치 수동 리셋 (관리자)
    """

    def __init__(
        self,
        store: SafetyStateStore,
        config: SafetyConfig | None = None,
        now_fn: NowFn | None = None,
    ) -> None:
        self._config    = config or SafetyConfig()
        self._daily_ks  = DailyKillSwitch(store, self._config, now_fn)
        self._weekly_ks = WeeklyKillSwitch(store, self._config, now_fn)
        self._drawdown  = DrawdownProtection(store, self._config)
        self._emergency = EmergencyShutdown(store, now_fn)
        self._disconnect = ExchangeDisconnectProtection(store, self._config, now_fn)

    async def check_order_allowed(self, user_id: str) -> SafetyCheckResult:
        """
        신규 주문 허용 여부를 확인한다.
        Risk Agent 승인 이후 거래소 주문 실행 직전에 반드시 호출한다.
        """
        # CHECK 1: 마스터 스위치
        if not self._config.live_trading_enabled:
            obs.record_safety_gate(allowed=False, halt_reason=HaltReason.LIVE_TRADING_DISABLED)
            return SafetyCheckResult(
                allowed=False,
                halt_reason=HaltReason.LIVE_TRADING_DISABLED,
                message="라이브 트레이딩 비활성화됨 (LIVE_TRADING_ENABLED=false)",
                alert_level=AlertLevel.INFO,
            )

        # CHECK 2: 긴급 중단 (전역)
        result = await self._emergency.check()
        if not result.allowed:
            logger.warning("safety_gate_blocked user=%s reason=EMERGENCY", user_id)
            obs.record_safety_gate(allowed=False, halt_reason=HaltReason.EMERGENCY_SHUTDOWN)
            obs.record_safety_halt(scope="global", reason="EMERGENCY_SHUTDOWN", active=True)
            return result

        # CHECK 3: 거래소 연결 오류 보호 (전역)
        result = await self._disconnect.check()
        if not result.allowed:
            logger.warning("safety_gate_blocked user=%s reason=DISCONNECT", user_id)
            obs.record_safety_gate(allowed=False, halt_reason=HaltReason.CONSECUTIVE_API_FAILURES)
            obs.record_safety_halt(scope="global", reason="CONSECUTIVE_API_FAILURES", active=True)
            return result

        # CHECK 4: 일일 손실 킬스위치 (사용자별)
        result = await self._daily_ks.check(user_id)
        if not result.allowed:
            logger.warning("safety_gate_blocked user=%s reason=DAILY_LOSS", user_id)
            obs.record_safety_gate(allowed=False, halt_reason=HaltReason.DAILY_LOSS_LIMIT)
            obs.record_safety_halt(scope=f"user:{user_id}", reason="DAILY_LOSS_LIMIT", active=True)
            return result

        # CHECK 5: 주간 손실 킬스위치 (사용자별)
        result = await self._weekly_ks.check(user_id)
        if not result.allowed:
            logger.warning("safety_gate_blocked user=%s reason=WEEKLY_LOSS", user_id)
            obs.record_safety_gate(allowed=False, halt_reason=HaltReason.WEEKLY_LOSS_LIMIT)
            obs.record_safety_halt(scope=f"user:{user_id}", reason="WEEKLY_LOSS_LIMIT", active=True)
            return result

        # CHECK 6: 드로우다운 보호 (사용자별)
        result = await self._drawdown.check(user_id)
        if not result.allowed:
            logger.warning("safety_gate_blocked user=%s reason=DRAWDOWN", user_id)
            obs.record_safety_gate(allowed=False, halt_reason=HaltReason.DRAWDOWN_PROTECTION)
            obs.record_safety_halt(scope=f"user:{user_id}", reason="DRAWDOWN_PROTECTION", active=True)
            return result

        obs.record_safety_gate(allowed=True)
        return SafetyCheckResult(allowed=True, message="OK")

    # ── 이벤트 핸들러 ──────────────────────────────────────────────────────────

    async def on_trade_closed(
        self,
        user_id: str,
        pnl_usdt: float,             # 음수 = 손실
        period_start_balance: float,  # 당일 00:00 UTC 기준 잔고
        week_start_balance: float,    # 당주 월요일 00:00 UTC 기준 잔고
        current_balance: float,       # 거래 종료 후 현재 잔고
    ) -> list[SafetyCheckResult]:
        """
        거래 종료 후 모든 손실 추적기를 업데이트한다.
        경고 포함 전체 결과 목록을 반환한다.
        """
        results: list[SafetyCheckResult] = []
        loss_usdt = abs(pnl_usdt) if pnl_usdt < 0 else 0.0

        if loss_usdt > 0:
            daily_result = await self._daily_ks.record_loss(
                user_id, loss_usdt, period_start_balance
            )
            results.append(daily_result)

            weekly_result = await self._weekly_ks.record_loss(
                user_id, loss_usdt, week_start_balance
            )
            results.append(weekly_result)

        drawdown_result = await self._drawdown.update_balance(user_id, current_balance)
        results.append(drawdown_result)

        return results

    async def on_api_failure(self) -> SafetyCheckResult:
        """API 실패를 기록하고 연결 오류 보호 상태를 반환한다."""
        return await self._disconnect.record_api_failure()

    async def on_api_success(self) -> None:
        """API 성공을 기록하여 연속 실패 카운터를 리셋한다."""
        await self._disconnect.record_api_success()

    async def trigger_emergency(
        self,
        reason: str,
        activated_by: str = "system",
    ) -> None:
        """긴급 중단을 발동한다. 수동 해제 전까지 모든 주문이 차단된다."""
        await self._emergency.activate(reason, activated_by)

    async def deactivate_emergency(self) -> None:
        """긴급 중단을 수동으로 해제한다."""
        await self._emergency.deactivate()

    async def resume_drawdown(self, user_id: str) -> None:
        """드로우다운 보호를 수동으로 재활성화한다."""
        await self._drawdown.resume(user_id)

    async def reset_daily_switch(self, user_id: str) -> None:
        """일일 킬스위치를 관리자가 수동으로 리셋한다."""
        await self._daily_ks.reset(user_id)

    async def reset_weekly_switch(self, user_id: str) -> None:
        """주간 킬스위치를 관리자가 수동으로 리셋한다."""
        await self._weekly_ks.reset(user_id)

    async def get_halt_status(self, user_id: str) -> UserHaltStatus:
        """
        사용자 Kill switch 중단 상태를 읽기 전용으로 반환한다.

        check_order_allowed()와 달리 Redis 상태를 변경하지 않는다.
        드로우다운 / 긴급 중단은 포함하지 않는다 — 이 둘은 관리자 해제 대상이며
        사용자가 직접 재개할 수 없다.
        """
        now   = self._daily_ks._now()
        store = self._daily_ks._store

        daily = await store.get_daily_kill_switch(user_id)
        if daily.is_halted and (daily.halt_until is None or now < daily.halt_until):
            return UserHaltStatus(
                is_halted=True,
                halt_reason=HaltReason.DAILY_LOSS_LIMIT,
                halt_until=daily.halt_until,
            )

        weekly = await store.get_weekly_kill_switch(user_id)
        if weekly.is_halted and (weekly.halt_until is None or now < weekly.halt_until):
            return UserHaltStatus(
                is_halted=True,
                halt_reason=HaltReason.WEEKLY_LOSS_LIMIT,
                halt_until=weekly.halt_until,
            )

        return UserHaltStatus(is_halted=False)
