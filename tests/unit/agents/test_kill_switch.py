"""Kill Switch 및 Halt 관리 단위 테스트."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from agents.risk.kill_switch import HaltTrigger, KillSwitch
from agents.risk.models import HaltState


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=False)
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def kill_switch(mock_redis):
    return KillSwitch(mock_redis)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


class TestGlobalKillSwitch:
    async def test_activate_global(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock
    ) -> None:
        await kill_switch.activate_global("시스템 점검")
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert "risk:kill_switch:global" in str(call_args)

    async def test_is_global_active_false_when_not_set(
        self, kill_switch: KillSwitch
    ) -> None:
        result = await kill_switch.is_global_active()
        assert result is False

    async def test_is_global_active_true_when_set(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock
    ) -> None:
        mock_redis.exists.return_value = True
        result = await kill_switch.is_global_active()
        assert result is True

    async def test_deactivate_global_deletes_key(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock
    ) -> None:
        await kill_switch.deactivate_global()
        mock_redis.delete.assert_called()


class TestUserKillSwitch:
    async def test_activate_user(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        await kill_switch.activate_user(user_id, "테스트")
        mock_redis.set.assert_called()

    async def test_deactivate_user(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        await kill_switch.deactivate_user(user_id)
        mock_redis.delete.assert_called()


class TestHaltTrading:
    async def test_halt_daily_loss(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        state = await kill_switch.halt_trading(
            user_id, HaltTrigger.DAILY_LOSS_LIMIT, "테스트 손실"
        )
        assert state.is_halted is True
        assert state.trigger == HaltTrigger.DAILY_LOSS_LIMIT.value
        assert state.until != "manual_resume"  # 자정까지

    async def test_halt_consecutive_losses_is_manual_resume(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        state = await kill_switch.halt_trading(
            user_id, HaltTrigger.CONSECUTIVE_LOSSES
        )
        assert state.until == "manual_resume"

    async def test_resume_trading_clears_all_keys(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        await kill_switch.resume_trading(user_id)
        mock_redis.delete.assert_called()


class TestGetHaltState:
    async def test_clean_state_not_halted(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        state = await kill_switch.get_halt_state(user_id)
        assert state.is_halted is False

    async def test_global_kill_switch_detected(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        mock_redis.exists.return_value = True
        state = await kill_switch.get_halt_state(user_id)
        assert state.is_halted is True
        assert state.is_global is True


class TestCooldown:
    async def test_set_cooldown_stores_end_time(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        end_time = await kill_switch.set_cooldown(user_id, 30)
        assert "T" in end_time   # ISO 8601 형식
        mock_redis.set.assert_called()

    async def test_clear_cooldown_deletes_key(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        await kill_switch.clear_cooldown(user_id)
        mock_redis.delete.assert_called()

    async def test_emergency_stop_activates_halt(
        self, kill_switch: KillSwitch, mock_redis: AsyncMock, user_id: uuid.UUID
    ) -> None:
        state = await kill_switch.emergency_stop(
            user_id, "긴급 상황", HaltTrigger.SYSTEM_ERROR
        )
        assert state.is_halted is True
        assert state.until == "manual_resume"
