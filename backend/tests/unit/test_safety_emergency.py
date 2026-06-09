"""
긴급 중단 단위 테스트 (8 tests).

검증 대상:
  - EmergencyShutdown:
      초기 비활성, activate(), check() 차단, deactivate(), is_active()
      발동자(user/system) 구분, 사유 메시지 포함 여부
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.safety.emergency import EmergencyShutdown
from app.safety.state import InMemorySafetyStateStore
from app.safety.types import HaltReason

UTC = timezone.utc


def _make(now: datetime | None = None) -> EmergencyShutdown:
    now_fn = (lambda: now) if now else None
    return EmergencyShutdown(InMemorySafetyStateStore(), now_fn=now_fn)


class TestEmergencyShutdown:

    async def test_initial_state_is_not_active(self) -> None:
        em = _make()
        result = await em.check()
        assert result.allowed is True

    async def test_is_active_returns_false_initially(self) -> None:
        em = _make()
        assert await em.is_active() is False

    async def test_activate_blocks_check(self) -> None:
        em = _make()
        await em.activate("강제청산 발생")
        result = await em.check()
        assert result.allowed is False
        assert result.halt_reason == HaltReason.EMERGENCY_SHUTDOWN

    async def test_is_active_returns_true_after_activate(self) -> None:
        em = _make()
        await em.activate("시스템 오류")
        assert await em.is_active() is True

    async def test_message_includes_reason(self) -> None:
        em = _make()
        await em.activate("비정상 포지션 감지")
        result = await em.check()
        assert "비정상 포지션 감지" in result.message

    async def test_message_includes_activated_by(self) -> None:
        em = _make()
        await em.activate("사용자 요청", activated_by="user")
        result = await em.check()
        assert "user" in result.message

    async def test_deactivate_allows_orders(self) -> None:
        em = _make()
        await em.activate("강제청산")
        await em.deactivate()
        result = await em.check()
        assert result.allowed is True

    async def test_deactivate_clears_is_active(self) -> None:
        em = _make()
        await em.activate("오류")
        await em.deactivate()
        assert await em.is_active() is False
