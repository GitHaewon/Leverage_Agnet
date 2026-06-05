"""
Kill Switch & Emergency Stop 관리.

Redis 기반 빠른 상태 조회.
거래 중단 상태는 Redis에만 저장하고 DB audit_logs에 영구 기록.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum

import redis.asyncio as aioredis

from agents.risk.constants import (
    CLOSEALL_CONFIRMATION_KEYWORD,
    REDIS_KEY_GLOBAL_KILL_SWITCH,
    REDIS_KEY_USER_COOLDOWN,
    REDIS_KEY_USER_HALT,
    REDIS_KEY_USER_KILL_SWITCH,
)
from agents.risk.models import HaltState

logger = logging.getLogger(__name__)


class HaltTrigger(str, Enum):
    DAILY_LOSS_LIMIT   = "DAILY_LOSS_LIMIT"    # §4
    WEEKLY_LOSS_LIMIT  = "WEEKLY_LOSS_LIMIT"   # §5
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"  # §6
    API_FAILURES       = "API_FAILURES"
    LIQUIDATION_EVENT  = "LIQUIDATION_EVENT"
    SYSTEM_ERROR       = "SYSTEM_ERROR"
    MANUAL             = "MANUAL"


# 중단 지속 시간 설정
_HALT_DURATION: dict[HaltTrigger, str] = {
    HaltTrigger.DAILY_LOSS_LIMIT:   "midnight_utc",
    HaltTrigger.WEEKLY_LOSS_LIMIT:  "next_monday_utc",
    HaltTrigger.CONSECUTIVE_LOSSES: "manual_resume",
    HaltTrigger.API_FAILURES:       "30_minutes",
    HaltTrigger.LIQUIDATION_EVENT:  "manual_resume",
    HaltTrigger.SYSTEM_ERROR:       "manual_resume",
    HaltTrigger.MANUAL:             "manual_resume",
}

# 중단 시 기존 포지션 청산 여부 (§9.3)
_HALT_CLOSES_EXISTING: dict[HaltTrigger, bool] = {
    HaltTrigger.DAILY_LOSS_LIMIT:   False,
    HaltTrigger.WEEKLY_LOSS_LIMIT:  False,
    HaltTrigger.CONSECUTIVE_LOSSES: False,
    HaltTrigger.API_FAILURES:       False,
    HaltTrigger.LIQUIDATION_EVENT:  True,
    HaltTrigger.SYSTEM_ERROR:       True,
    HaltTrigger.MANUAL:             False,
}


def _until_midnight_utc() -> str:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # 이미 자정이 지난 경우 다음날 자정
    import calendar
    from datetime import timedelta
    next_midnight = midnight + timedelta(days=1)
    return next_midnight.isoformat()


def _until_next_monday_utc() -> str:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    days_until_monday = (7 - now.weekday()) % 7 or 7
    next_monday = (now + timedelta(days=days_until_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return next_monday.isoformat()


def _until_30_minutes() -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()


def _compute_until(trigger: HaltTrigger) -> str:
    mapping = {
        "midnight_utc": _until_midnight_utc,
        "next_monday_utc": _until_next_monday_utc,
        "30_minutes": _until_30_minutes,
        "manual_resume": lambda: "manual_resume",
    }
    key = _HALT_DURATION[trigger]
    return mapping.get(key, lambda: "manual_resume")()


class KillSwitch:
    """
    Kill Switch & Trading Halt 관리.

    계층:
      1. global kill switch → 시스템 전체
      2. user kill switch   → 특정 사용자
      3. halt               → 트리거별 중단 (기간 설정)
      4. cooldown           → 연속 손실 30분 쿨다운 (자동 해제)
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    # ── Global Kill Switch ────────────────────────────────────────────────────

    async def activate_global(self, reason: str = "") -> None:
        """시스템 전체 거래 즉시 중단."""
        await self._redis.set(
            REDIS_KEY_GLOBAL_KILL_SWITCH,
            json.dumps({"reason": reason, "activated_at": datetime.now(timezone.utc).isoformat()}),
        )
        logger.critical("GLOBAL KILL SWITCH ACTIVATED reason=%s", reason)

    async def deactivate_global(self) -> None:
        await self._redis.delete(REDIS_KEY_GLOBAL_KILL_SWITCH)
        logger.info("Global kill switch deactivated")

    async def is_global_active(self) -> bool:
        return bool(await self._redis.exists(REDIS_KEY_GLOBAL_KILL_SWITCH))

    # ── User Kill Switch ──────────────────────────────────────────────────────

    async def activate_user(self, user_id: uuid.UUID, reason: str = "") -> None:
        """특정 사용자 거래 즉시 중단."""
        key = REDIS_KEY_USER_KILL_SWITCH.format(user_id=user_id)
        await self._redis.set(
            key,
            json.dumps({"reason": reason, "activated_at": datetime.now(timezone.utc).isoformat()}),
        )
        logger.warning("User kill switch activated user_id=%s reason=%s", user_id, reason)

    async def deactivate_user(self, user_id: uuid.UUID) -> None:
        key = REDIS_KEY_USER_KILL_SWITCH.format(user_id=user_id)
        await self._redis.delete(key)

    async def is_user_active(self, user_id: uuid.UUID) -> bool:
        key = REDIS_KEY_USER_KILL_SWITCH.format(user_id=user_id)
        return bool(await self._redis.exists(key))

    # ── Trading Halt ──────────────────────────────────────────────────────────

    async def halt_trading(
        self,
        user_id: uuid.UUID,
        trigger: HaltTrigger,
        extra_reason: str = "",
    ) -> HaltState:
        """거래 중단 — 기간은 트리거별로 자동 결정."""
        until = _compute_until(trigger)
        data = {
            "trigger": trigger.value,
            "reason": extra_reason,
            "until": until,
            "halted_at": datetime.now(timezone.utc).isoformat(),
            "closes_existing": _HALT_CLOSES_EXISTING.get(trigger, False),
        }
        halt_key = REDIS_KEY_USER_HALT.format(user_id=user_id)

        # TTL 설정: 기간이 있으면 TTL, manual_resume은 TTL 없음
        if until == "manual_resume":
            await self._redis.set(halt_key, json.dumps(data))
        else:
            try:
                end_dt = datetime.fromisoformat(until)
                ttl = max(1, int((end_dt - datetime.now(timezone.utc)).total_seconds()))
                await self._redis.set(halt_key, json.dumps(data), ex=ttl)
            except ValueError:
                await self._redis.set(halt_key, json.dumps(data))

        logger.warning(
            "Trading halted user_id=%s trigger=%s until=%s",
            user_id, trigger.value, until,
        )
        return HaltState(
            is_halted=True,
            trigger=trigger.value,
            reason=extra_reason,
            until=until,
        )

    async def resume_trading(self, user_id: uuid.UUID) -> None:
        """수동 거래 재활성화 (체크리스트 확인 후 호출)."""
        halt_key = REDIS_KEY_USER_HALT.format(user_id=user_id)
        user_key = REDIS_KEY_USER_KILL_SWITCH.format(user_id=user_id)
        cooldown_key = REDIS_KEY_USER_COOLDOWN.format(user_id=user_id)
        await self._redis.delete(halt_key, user_key, cooldown_key)
        logger.info("Trading resumed user_id=%s", user_id)

    async def get_halt_state(self, user_id: uuid.UUID) -> HaltState:
        # Global kill switch
        if await self.is_global_active():
            return HaltState(is_halted=True, trigger="GLOBAL", reason="시스템 전체 중단", is_global=True)

        # User kill switch
        if await self.is_user_active(user_id):
            key = REDIS_KEY_USER_KILL_SWITCH.format(user_id=user_id)
            raw = await self._redis.get(key)
            reason = json.loads(raw).get("reason", "") if raw else ""
            return HaltState(is_halted=True, trigger="MANUAL", reason=reason)

        # Halt 상태
        halt_key = REDIS_KEY_USER_HALT.format(user_id=user_id)
        raw = await self._redis.get(halt_key)
        if raw:
            data = json.loads(raw)
            return HaltState(
                is_halted=True,
                trigger=data.get("trigger"),
                reason=data.get("reason", ""),
                until=data.get("until"),
            )

        return HaltState(is_halted=False)

    # ── Emergency Stop ────────────────────────────────────────────────────────

    async def emergency_stop(
        self,
        user_id: uuid.UUID,
        reason: str,
        trigger: HaltTrigger = HaltTrigger.MANUAL,
    ) -> HaltState:
        """
        긴급 거래 중단.
        1. 즉각 Kill Switch 활성화
        2. Halt 상태 기록
        3. 기존 포지션 청산 여부는 호출자가 결정
        """
        await self.activate_user(user_id, reason)
        state = await self.halt_trading(user_id, trigger, reason)
        logger.critical(
            "EMERGENCY STOP user_id=%s trigger=%s reason=%s",
            user_id, trigger.value, reason,
        )
        return state

    # ── Cooldown (연속 손실) ───────────────────────────────────────────────────

    async def set_cooldown(self, user_id: uuid.UUID, minutes: int) -> str:
        from datetime import timedelta
        end = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        key = REDIS_KEY_USER_COOLDOWN.format(user_id=user_id)
        await self._redis.set(key, end.isoformat(), ex=minutes * 60)
        return end.isoformat()

    async def clear_cooldown(self, user_id: uuid.UUID) -> None:
        key = REDIS_KEY_USER_COOLDOWN.format(user_id=user_id)
        await self._redis.delete(key)

    async def get_cooldown_end(self, user_id: uuid.UUID) -> str | None:
        key = REDIS_KEY_USER_COOLDOWN.format(user_id=user_id)
        return await self._redis.get(key)
