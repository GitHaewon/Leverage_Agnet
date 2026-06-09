"""
C-03 단위 테스트 — RedisSafetyStateStore.

검증 항목:
  1. 기본 CRUD (daily/weekly/disconnect/emergency/drawdown)
  2. 공유 키 동기화: daily halt → risk:halt:{user_id} 쓰기
  3. 공유 키 동기화: weekly halt → risk:halt:{user_id} 쓰기
  4. 공유 키 보호: RiskEngine이 쓴 non-safety 트리거는 삭제하지 않음
  5. 공유 키 해제: daily+weekly 모두 해제 시에만 risk:halt 삭제
  6. emergency → risk:kill_switch:global 쓰기/삭제
  7. Fallback: risk:halt:{user_id}에서 KillSwitchState 복원
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.safety.state import RedisSafetyStateStore
from app.safety.types import (
    DisconnectState,
    DrawdownState,
    EmergencyState,
    HaltReason,
    KillSwitchState,
)

UID = str(uuid.uuid4())
NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
HALT_UNTIL = NOW + timedelta(hours=8)


# ── Redis Mock 팩토리 ─────────────────────────────────────────────────────────────

def _make_redis() -> AsyncMock:
    """AsyncMock으로 aioredis.Redis를 모사한다."""
    store: dict[str, str] = {}

    redis = AsyncMock()

    async def _set(key, value, ex=None):
        store[key] = value

    async def _get(key):
        return store.get(key)

    async def _delete(*keys):
        for k in keys:
            store.pop(k, None)

    async def _exists(key):
        return 1 if key in store else 0

    redis.set = AsyncMock(side_effect=_set)
    redis.get = AsyncMock(side_effect=_get)
    redis.delete = AsyncMock(side_effect=_delete)
    redis.exists = AsyncMock(side_effect=_exists)
    redis._store = store   # 검증용 내부 접근
    return redis


# ── Daily Kill Switch ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_default_not_halted():
    r = _make_redis()
    store = RedisSafetyStateStore(r)
    state = await store.get_daily_kill_switch(UID)
    assert state.is_halted is False
    assert state.current_loss_usdt == 0.0


@pytest.mark.asyncio
async def test_daily_round_trip():
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    written = KillSwitchState(
        user_id=UID,
        is_halted=False,
        current_loss_usdt=150.0,
        period_start_balance=10000.0,
    )
    await store.set_daily_kill_switch(UID, written)
    read = await store.get_daily_kill_switch(UID)

    assert read.current_loss_usdt == 150.0
    assert read.period_start_balance == 10000.0
    assert read.is_halted is False


@pytest.mark.asyncio
async def test_daily_halt_writes_shared_halt_key():
    """daily halt 활성화 → risk:halt:{user_id} 에 쓰여야 한다."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    halted = KillSwitchState(
        user_id=UID,
        is_halted=True,
        halt_reason=HaltReason.DAILY_LOSS_LIMIT,
        halt_until=HALT_UNTIL,
        current_loss_usdt=300.0,
    )
    await store.set_daily_kill_switch(UID, halted)

    shared_key = f"risk:halt:{UID}"
    assert shared_key in r._store

    data = json.loads(r._store[shared_key])
    assert data["trigger"] == "DAILY_LOSS_LIMIT"
    assert data["closes_existing"] is False


@pytest.mark.asyncio
async def test_daily_reset_clears_shared_halt_when_weekly_also_clear():
    """daily 해제 + weekly도 clear → risk:halt 삭제."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    # halt 설정
    await store.set_daily_kill_switch(UID, KillSwitchState(
        user_id=UID, is_halted=True, halt_reason=HaltReason.DAILY_LOSS_LIMIT
    ))

    shared_key = f"risk:halt:{UID}"
    assert shared_key in r._store

    # 리셋
    await store.set_daily_kill_switch(UID, KillSwitchState(user_id=UID, is_halted=False))
    assert shared_key not in r._store


@pytest.mark.asyncio
async def test_daily_reset_keeps_shared_halt_when_weekly_still_halted():
    """daily 해제 but weekly는 여전히 halted → risk:halt 유지."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    # weekly를 먼저 halt
    await store.set_weekly_kill_switch(UID, KillSwitchState(
        user_id=UID, is_halted=True, halt_reason=HaltReason.WEEKLY_LOSS_LIMIT
    ))

    # daily도 halt
    await store.set_daily_kill_switch(UID, KillSwitchState(
        user_id=UID, is_halted=True, halt_reason=HaltReason.DAILY_LOSS_LIMIT
    ))

    # daily만 리셋
    await store.set_daily_kill_switch(UID, KillSwitchState(user_id=UID, is_halted=False))

    # weekly가 halted이므로 공유 키는 유지되어야 함
    shared_key = f"risk:halt:{UID}"
    assert shared_key in r._store


@pytest.mark.asyncio
async def test_shared_halt_set_by_risk_engine_not_deleted():
    """RiskEngine이 CONSECUTIVE_LOSSES 트리거로 쓴 risk:halt는 SafetyGate가 삭제하면 안 됨."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    # RiskEngine이 직접 쓴 것처럼 시뮬레이션
    shared_key = f"risk:halt:{UID}"
    r._store[shared_key] = json.dumps({
        "trigger": "CONSECUTIVE_LOSSES",
        "reason": "3연패",
        "until": "manual_resume",
        "halted_at": NOW.isoformat(),
        "closes_existing": False,
    })

    # SafetyGate daily를 halt 후 리셋
    await store.set_daily_kill_switch(UID, KillSwitchState(
        user_id=UID, is_halted=True, halt_reason=HaltReason.DAILY_LOSS_LIMIT
    ))
    await store.set_daily_kill_switch(UID, KillSwitchState(user_id=UID, is_halted=False))

    # CONSECUTIVE_LOSSES 키는 삭제되면 안 됨
    assert shared_key in r._store
    data = json.loads(r._store[shared_key])
    assert data["trigger"] == "CONSECUTIVE_LOSSES"


# ── Fallback: risk:halt → KillSwitchState 복원 ────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_reads_daily_halt_from_risk_layer():
    """safety:ks:daily가 없어도 risk:halt에서 DAILY_LOSS_LIMIT 복원."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    shared_key = f"risk:halt:{UID}"
    r._store[shared_key] = json.dumps({
        "trigger": "DAILY_LOSS_LIMIT",
        "reason": "RiskEngine이 직접 설정",
        "until": HALT_UNTIL.isoformat(),
        "halted_at": NOW.isoformat(),
        "closes_existing": False,
    })

    state = await store.get_daily_kill_switch(UID)
    assert state.is_halted is True
    assert state.halt_reason == HaltReason.DAILY_LOSS_LIMIT


@pytest.mark.asyncio
async def test_fallback_ignores_weekly_trigger_for_daily():
    """risk:halt의 trigger가 WEEKLY이면 daily에서는 not halted로 반환."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    r._store[f"risk:halt:{UID}"] = json.dumps({
        "trigger": "WEEKLY_LOSS_LIMIT",
        "until": HALT_UNTIL.isoformat(),
    })

    state = await store.get_daily_kill_switch(UID)
    assert state.is_halted is False


# ── Weekly Kill Switch ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_weekly_halt_writes_shared_halt_key():
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    await store.set_weekly_kill_switch(UID, KillSwitchState(
        user_id=UID, is_halted=True, halt_reason=HaltReason.WEEKLY_LOSS_LIMIT
    ))

    data = json.loads(r._store[f"risk:halt:{UID}"])
    assert data["trigger"] == "WEEKLY_LOSS_LIMIT"


# ── Emergency State ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_activate_writes_global_key():
    """emergency 활성 → risk:kill_switch:global 쓰기."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    state = EmergencyState(
        is_active=True,
        activated_at=NOW,
        activated_by="system",
        reason="강제청산",
    )
    await store.set_emergency_state(state)

    assert "risk:kill_switch:global" in r._store
    data = json.loads(r._store["risk:kill_switch:global"])
    assert data["reason"] == "강제청산"


@pytest.mark.asyncio
async def test_emergency_deactivate_deletes_global_key():
    """emergency 해제 → risk:kill_switch:global 삭제."""
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    await store.set_emergency_state(EmergencyState(is_active=True, reason="test"))
    assert "risk:kill_switch:global" in r._store

    await store.set_emergency_state(EmergencyState(is_active=False))
    assert "risk:kill_switch:global" not in r._store


@pytest.mark.asyncio
async def test_emergency_round_trip():
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    written = EmergencyState(
        is_active=True,
        activated_at=NOW,
        activated_by="user",
        reason="포지션 청산 감지",
    )
    await store.set_emergency_state(written)
    read = await store.get_emergency_state()

    assert read.is_active is True
    assert read.reason == "포지션 청산 감지"
    assert read.activated_by == "user"


# ── Disconnect / Drawdown ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disconnect_round_trip():
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    written = DisconnectState(consecutive_failures=3, is_halted=True)
    await store.set_disconnect_state(written)
    read = await store.get_disconnect_state()

    assert read.consecutive_failures == 3
    assert read.is_halted is True


@pytest.mark.asyncio
async def test_drawdown_round_trip():
    r = _make_redis()
    store = RedisSafetyStateStore(r)

    written = DrawdownState(peak_balance=10000.0, current_balance=8500.0, is_halted=True)
    await store.set_drawdown_state(UID, written)
    read = await store.get_drawdown_state(UID)

    assert read.peak_balance == 10000.0
    assert read.current_balance == 8500.0
    assert read.is_halted is True


@pytest.mark.asyncio
async def test_drawdown_default_for_unknown_user():
    r = _make_redis()
    store = RedisSafetyStateStore(r)
    state = await store.get_drawdown_state("unknown-user")
    assert state.peak_balance == 0.0
    assert state.is_halted is False


# ── 공유 키 네임스페이스 일관성 확인 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shared_key_namespace_matches_risk_engine_constants():
    """
    RedisSafetyStateStore가 쓰는 공유 키가
    agents/risk/constants.py의 REDIS_KEY_USER_HALT, REDIS_KEY_GLOBAL_KILL_SWITCH와 일치하는지 확인.
    """
    from app.safety import state as state_module

    assert state_module._SHARED_HALT == "risk:halt:{user_id}"
    assert state_module._SHARED_GLOBAL == "risk:kill_switch:global"


@pytest.mark.asyncio
async def test_halt_state_persists_across_store_instances():
    """
    같은 Redis 인스턴스를 공유하는 두 store가 동일한 halt 상태를 읽는다.
    Worker 재시작 후 상태 유지를 시뮬레이션한다.
    """
    r = _make_redis()

    # 첫 번째 store (예: Worker 재시작 전)
    store_before = RedisSafetyStateStore(r)
    await store_before.set_daily_kill_switch(UID, KillSwitchState(
        user_id=UID, is_halted=True, halt_reason=HaltReason.DAILY_LOSS_LIMIT,
        current_loss_usdt=400.0,
    ))

    # 두 번째 store (예: Worker 재시작 후 새로 생성)
    store_after = RedisSafetyStateStore(r)
    recovered = await store_after.get_daily_kill_switch(UID)

    assert recovered.is_halted is True
    assert recovered.halt_reason == HaltReason.DAILY_LOSS_LIMIT
    assert recovered.current_loss_usdt == 400.0
