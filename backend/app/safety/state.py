"""
Live Trading Safety Layer — 상태 저장소.

SafetyStateStore:      추상 인터페이스
RedisSafetyStateStore: 프로덕션 Redis 구현 (재시작 후 상태 유지)
InMemorySafetyStateStore: 단위 테스트 전용

공유 Redis 키 (agents/risk/kill_switch.KillSwitch와 동일 네임스페이스):
  risk:halt:{user_id}          — 사용자별 halt 상태 (SafetyGate + RiskEngine 공동 읽기/쓰기)
  risk:kill_switch:global      — 전역 kill switch (SafetyGate + RiskEngine 공동 읽기/쓰기)

이 두 키를 통해 SafetyGate.check_order_allowed()와
RiskEngine.validate()가 항상 동일한 halt 상태를 본다.
"""
from __future__ import annotations

import abc
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from .types import DisconnectState, DrawdownState, EmergencyState, HaltReason, KillSwitchState

logger = logging.getLogger(__name__)

# ── Redis 키 (agents/risk/constants.py와 일치해야 함) ────────────────────────────
_SHARED_HALT    = "risk:halt:{user_id}"       # agents/risk/constants.REDIS_KEY_USER_HALT
_SHARED_GLOBAL  = "risk:kill_switch:global"   # agents/risk/constants.REDIS_KEY_GLOBAL_KILL_SWITCH

# SafetyStateStore 전용 키 (손실 누적 등 상세 상태)
_DAILY_KS    = "safety:ks:daily:{user_id}"
_WEEKLY_KS   = "safety:ks:weekly:{user_id}"
_DISCONNECT  = "safety:disconnect"
_EMERGENCY   = "safety:emergency"
_DRAWDOWN    = "safety:drawdown:{user_id}"

# SafetyGate가 공유 키에 쓸 때 사용하는 트리거 값
_SAFETY_TRIGGERS = frozenset({"DAILY_LOSS_LIMIT", "WEEKLY_LOSS_LIMIT"})


class SafetyStateStore(abc.ABC):
    """Safety Layer 상태 저장소 추상 인터페이스."""

    @abc.abstractmethod
    async def get_daily_kill_switch(self, user_id: str) -> KillSwitchState: ...

    @abc.abstractmethod
    async def set_daily_kill_switch(self, user_id: str, state: KillSwitchState) -> None: ...

    @abc.abstractmethod
    async def get_weekly_kill_switch(self, user_id: str) -> KillSwitchState: ...

    @abc.abstractmethod
    async def set_weekly_kill_switch(self, user_id: str, state: KillSwitchState) -> None: ...

    @abc.abstractmethod
    async def get_disconnect_state(self) -> DisconnectState: ...

    @abc.abstractmethod
    async def set_disconnect_state(self, state: DisconnectState) -> None: ...

    @abc.abstractmethod
    async def get_emergency_state(self) -> EmergencyState: ...

    @abc.abstractmethod
    async def set_emergency_state(self, state: EmergencyState) -> None: ...

    @abc.abstractmethod
    async def get_drawdown_state(self, user_id: str) -> DrawdownState: ...

    @abc.abstractmethod
    async def set_drawdown_state(self, user_id: str, state: DrawdownState) -> None: ...


# ── 직렬화 헬퍼 ──────────────────────────────────────────────────────────────────

def _ks_to_json(state: KillSwitchState) -> dict:
    return {
        "is_halted": state.is_halted,
        "halt_reason": state.halt_reason.value if state.halt_reason else None,
        "halt_until": state.halt_until.isoformat() if state.halt_until else None,
        "current_loss_usdt": state.current_loss_usdt,
        "period_start_balance": state.period_start_balance,
    }


def _ks_from_json(user_id: str, data: dict) -> KillSwitchState:
    halt_until: datetime | None = None
    if data.get("halt_until"):
        try:
            halt_until = datetime.fromisoformat(data["halt_until"])
        except ValueError:
            pass

    halt_reason: HaltReason | None = None
    if data.get("halt_reason"):
        try:
            halt_reason = HaltReason(data["halt_reason"])
        except ValueError:
            pass

    return KillSwitchState(
        user_id=user_id,
        is_halted=data.get("is_halted", False),
        halt_reason=halt_reason,
        halt_until=halt_until,
        current_loss_usdt=data.get("current_loss_usdt", 0.0),
        period_start_balance=data.get("period_start_balance", 0.0),
    )


def _ks_from_risk_halt(user_id: str, data: dict, reason: HaltReason) -> KillSwitchState:
    """RiskEngine이 쓴 risk:halt:{user_id} 형식에서 KillSwitchState 복원."""
    until_str = data.get("until", "")
    halt_until: datetime | None = None
    if until_str and until_str != "manual_resume":
        try:
            halt_until = datetime.fromisoformat(until_str)
        except ValueError:
            pass
    return KillSwitchState(
        user_id=user_id,
        is_halted=True,
        halt_reason=reason,
        halt_until=halt_until,
        current_loss_usdt=0.0,
        period_start_balance=0.0,
    )


def _compute_ttl(halt_until: datetime | None) -> int | None:
    if halt_until is None:
        return None
    remaining = int((halt_until - datetime.now(timezone.utc)).total_seconds())
    return max(1, remaining)


def _disconnect_to_json(s: DisconnectState) -> dict:
    return {
        "consecutive_failures": s.consecutive_failures,
        "last_failure_at": s.last_failure_at.isoformat() if s.last_failure_at else None,
        "halt_until": s.halt_until.isoformat() if s.halt_until else None,
        "is_halted": s.is_halted,
    }


def _disconnect_from_json(data: dict) -> DisconnectState:
    return DisconnectState(
        consecutive_failures=data.get("consecutive_failures", 0),
        last_failure_at=(
            datetime.fromisoformat(data["last_failure_at"])
            if data.get("last_failure_at") else None
        ),
        halt_until=(
            datetime.fromisoformat(data["halt_until"])
            if data.get("halt_until") else None
        ),
        is_halted=data.get("is_halted", False),
    )


def _emergency_to_json(s: EmergencyState) -> dict:
    return {
        "is_active": s.is_active,
        "activated_at": s.activated_at.isoformat() if s.activated_at else None,
        "activated_by": s.activated_by,
        "reason": s.reason,
        "requires_manual_resume": s.requires_manual_resume,
    }


def _emergency_from_json(data: dict) -> EmergencyState:
    return EmergencyState(
        is_active=data.get("is_active", False),
        activated_at=(
            datetime.fromisoformat(data["activated_at"])
            if data.get("activated_at") else None
        ),
        activated_by=data.get("activated_by"),
        reason=data.get("reason", ""),
        requires_manual_resume=data.get("requires_manual_resume", True),
    )


def _drawdown_to_json(s: DrawdownState) -> dict:
    return {
        "peak_balance": s.peak_balance,
        "current_balance": s.current_balance,
        "is_halted": s.is_halted,
        "warning_sent": s.warning_sent,
    }


def _drawdown_from_json(data: dict) -> DrawdownState:
    return DrawdownState(
        peak_balance=data.get("peak_balance", 0.0),
        current_balance=data.get("current_balance", 0.0),
        is_halted=data.get("is_halted", False),
        warning_sent=data.get("warning_sent", False),
    )


# ── RedisSafetyStateStore ────────────────────────────────────────────────────────

class RedisSafetyStateStore(SafetyStateStore):
    """
    프로덕션 Redis 기반 상태 저장소.

    모든 상태를 Redis에 저장해 Worker 재시작 후에도 halt 상태가 유지된다.

    공유 키 동기화:
      - daily/weekly halt 활성화 → risk:halt:{user_id} 쓰기
        → RiskEngine.check_kill_switch()가 이 키를 읽으므로 자동으로 같은 halt 상태를 본다.
      - emergency 활성화 → risk:kill_switch:global 쓰기
        → RiskEngine.check_kill_switch()의 전역 체크와 동기화된다.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis

    # ── Daily Kill Switch ──────────────────────────────────────────────────────

    async def get_daily_kill_switch(self, user_id: str) -> KillSwitchState:
        raw = await self._r.get(_DAILY_KS.format(user_id=user_id))
        if raw is not None:
            return _ks_from_json(user_id, json.loads(raw))

        # Fallback: RiskEngine이 직접 risk:halt:{user_id}에 쓴 경우 반영
        halt_raw = await self._r.get(_SHARED_HALT.format(user_id=user_id))
        if halt_raw:
            data = json.loads(halt_raw)
            if data.get("trigger") == "DAILY_LOSS_LIMIT":
                return _ks_from_risk_halt(user_id, data, HaltReason.DAILY_LOSS_LIMIT)

        return KillSwitchState(user_id=user_id)

    async def set_daily_kill_switch(self, user_id: str, state: KillSwitchState) -> None:
        await self._write_ks_key(_DAILY_KS.format(user_id=user_id), state)
        await self._sync_shared_halt(user_id, state, "DAILY_LOSS_LIMIT", _WEEKLY_KS)

    # ── Weekly Kill Switch ─────────────────────────────────────────────────────

    async def get_weekly_kill_switch(self, user_id: str) -> KillSwitchState:
        raw = await self._r.get(_WEEKLY_KS.format(user_id=user_id))
        if raw is not None:
            return _ks_from_json(user_id, json.loads(raw))

        halt_raw = await self._r.get(_SHARED_HALT.format(user_id=user_id))
        if halt_raw:
            data = json.loads(halt_raw)
            if data.get("trigger") == "WEEKLY_LOSS_LIMIT":
                return _ks_from_risk_halt(user_id, data, HaltReason.WEEKLY_LOSS_LIMIT)

        return KillSwitchState(user_id=user_id)

    async def set_weekly_kill_switch(self, user_id: str, state: KillSwitchState) -> None:
        await self._write_ks_key(_WEEKLY_KS.format(user_id=user_id), state)
        await self._sync_shared_halt(user_id, state, "WEEKLY_LOSS_LIMIT", _DAILY_KS)

    # ── Disconnect State ───────────────────────────────────────────────────────

    async def get_disconnect_state(self) -> DisconnectState:
        raw = await self._r.get(_DISCONNECT)
        return _disconnect_from_json(json.loads(raw)) if raw else DisconnectState()

    async def set_disconnect_state(self, state: DisconnectState) -> None:
        await self._r.set(_DISCONNECT, json.dumps(_disconnect_to_json(state)))

    # ── Emergency State ────────────────────────────────────────────────────────

    async def get_emergency_state(self) -> EmergencyState:
        raw = await self._r.get(_EMERGENCY)
        return _emergency_from_json(json.loads(raw)) if raw else EmergencyState()

    async def set_emergency_state(self, state: EmergencyState) -> None:
        await self._r.set(_EMERGENCY, json.dumps(_emergency_to_json(state)))

        # 전역 kill switch 공유 키 동기화 (RiskEngine.check_kill_switch() 호환)
        if state.is_active:
            payload = json.dumps({
                "reason": state.reason,
                "activated_at": state.activated_at.isoformat() if state.activated_at else "",
            })
            await self._r.set(_SHARED_GLOBAL, payload)
        else:
            await self._r.delete(_SHARED_GLOBAL)

    # ── Drawdown State ─────────────────────────────────────────────────────────

    async def get_drawdown_state(self, user_id: str) -> DrawdownState:
        raw = await self._r.get(_DRAWDOWN.format(user_id=user_id))
        return _drawdown_from_json(json.loads(raw)) if raw else DrawdownState()

    async def set_drawdown_state(self, user_id: str, state: DrawdownState) -> None:
        await self._r.set(
            _DRAWDOWN.format(user_id=user_id),
            json.dumps(_drawdown_to_json(state)),
        )

    # ── Private ───────────────────────────────────────────────────────────────

    async def _write_ks_key(self, key: str, state: KillSwitchState) -> None:
        ttl = _compute_ttl(state.halt_until)
        payload = json.dumps(_ks_to_json(state))
        if ttl is not None:
            await self._r.set(key, payload, ex=ttl)
        else:
            await self._r.set(key, payload)

    async def _sync_shared_halt(
        self,
        user_id: str,
        state: KillSwitchState,
        trigger: str,
        other_own_key_tpl: str,
    ) -> None:
        """
        risk:halt:{user_id}를 SafetyGate와 RiskEngine이 공유하는 상태로 유지한다.

        halt 활성화 시: 공유 키에 쓰기.
        halt 해제 시: 다른 쪽(daily↔weekly)이 여전히 halted인지 확인 후 삭제 결정.
        RiskEngine이 직접 다른 트리거(CONSECUTIVE_LOSSES 등)로 쓴 키는 건드리지 않는다.
        """
        shared_key = _SHARED_HALT.format(user_id=user_id)

        if state.is_halted:
            until_str = state.halt_until.isoformat() if state.halt_until else "manual_resume"
            payload = json.dumps({
                "trigger": trigger,
                "reason": "손실 한도 도달",
                "until": until_str,
                "halted_at": datetime.now(timezone.utc).isoformat(),
                "closes_existing": False,
            })
            ttl = _compute_ttl(state.halt_until)
            if ttl is not None:
                await self._r.set(shared_key, payload, ex=ttl)
            else:
                await self._r.set(shared_key, payload)
        else:
            # 공유 키가 safety layer(daily/weekly)가 쓴 것인지 확인
            shared_raw = await self._r.get(shared_key)
            if not shared_raw:
                return

            shared_data = json.loads(shared_raw)
            shared_trigger = shared_data.get("trigger", "")
            if shared_trigger not in _SAFETY_TRIGGERS:
                # RiskEngine이 다른 이유로 쓴 키 (CONSECUTIVE_LOSSES 등) → 건드리지 않음
                return

            # 상대방(daily↔weekly) halt 여부 확인
            other_raw = await self._r.get(other_own_key_tpl.format(user_id=user_id))
            other_halted = False
            if other_raw:
                other_data = json.loads(other_raw)
                other_halted = other_data.get("is_halted", False)

            if not other_halted:
                await self._r.delete(shared_key)


# ── InMemorySafetyStateStore (단위 테스트 전용) ──────────────────────────────────

class InMemorySafetyStateStore(SafetyStateStore):
    """
    단위 테스트 전용 인메모리 구현.

    프로덕션에서 사용 금지. 재시작 시 모든 상태가 초기화된다.
    프로덕션에서는 반드시 RedisSafetyStateStore를 사용한다.
    """

    def __init__(self) -> None:
        self._daily:      dict[str, KillSwitchState] = {}
        self._weekly:     dict[str, KillSwitchState] = {}
        self._disconnect  = DisconnectState()
        self._emergency   = EmergencyState()
        self._drawdown:   dict[str, DrawdownState]  = {}

    async def get_daily_kill_switch(self, user_id: str) -> KillSwitchState:
        return self._daily.get(user_id, KillSwitchState(user_id=user_id))

    async def set_daily_kill_switch(self, user_id: str, state: KillSwitchState) -> None:
        self._daily[user_id] = state

    async def get_weekly_kill_switch(self, user_id: str) -> KillSwitchState:
        return self._weekly.get(user_id, KillSwitchState(user_id=user_id))

    async def set_weekly_kill_switch(self, user_id: str, state: KillSwitchState) -> None:
        self._weekly[user_id] = state

    async def get_disconnect_state(self) -> DisconnectState:
        return self._disconnect

    async def set_disconnect_state(self, state: DisconnectState) -> None:
        self._disconnect = state

    async def get_emergency_state(self) -> EmergencyState:
        return self._emergency

    async def set_emergency_state(self, state: EmergencyState) -> None:
        self._emergency = state

    async def get_drawdown_state(self, user_id: str) -> DrawdownState:
        return self._drawdown.get(user_id, DrawdownState())

    async def set_drawdown_state(self, user_id: str, state: DrawdownState) -> None:
        self._drawdown[user_id] = state
