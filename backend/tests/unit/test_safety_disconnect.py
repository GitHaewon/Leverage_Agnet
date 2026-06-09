"""
거래소 연결 오류 보호 단위 테스트 (12 tests).

검증 대상:
  - ExchangeDisconnectProtection:
      연속 실패 카운터, 임계값 발동, 중단 중 추가 실패,
      성공 시 카운터 리셋, 중단 중 성공 무시, 만료 후 자동 재개
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.safety.disconnect import ExchangeDisconnectProtection
from app.safety.state import InMemorySafetyStateStore
from app.safety.types import HaltReason, SafetyConfig

UTC = timezone.utc


def _config(threshold: int = 3, halt_minutes: int = 30) -> SafetyConfig:
    return SafetyConfig(
        live_trading_enabled=True,
        api_failure_halt_threshold=threshold,
        api_failure_halt_minutes=halt_minutes,
    )


def _make(now: datetime, config: SafetyConfig | None = None) -> ExchangeDisconnectProtection:
    return ExchangeDisconnectProtection(
        InMemorySafetyStateStore(), config or _config(), now_fn=lambda: now
    )


class TestExchangeDisconnectProtection:

    async def test_no_failure_check_returns_allowed(self) -> None:
        dp = _make(datetime(2025, 6, 9, 12, 0, tzinfo=UTC))
        result = await dp.check()
        assert result.allowed is True

    async def test_first_failure_returns_allowed_with_warning(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        result = await dp.record_api_failure()
        assert result.allowed is True
        assert "1/3" in result.message

    async def test_second_failure_returns_allowed_with_warning(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        await dp.record_api_failure()
        result = await dp.record_api_failure()
        assert result.allowed is True
        assert "2/3" in result.message

    async def test_third_failure_triggers_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        await dp.record_api_failure()
        await dp.record_api_failure()
        result = await dp.record_api_failure()
        assert result.allowed is False
        assert result.halt_reason == HaltReason.CONSECUTIVE_API_FAILURES

    async def test_check_returns_blocked_during_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        for _ in range(3):
            await dp.record_api_failure()
        result = await dp.check()
        assert result.allowed is False

    async def test_check_auto_resumes_after_halt_duration(self) -> None:
        now_halt = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        store = InMemorySafetyStateStore()
        dp_halt = ExchangeDisconnectProtection(store, _config(), now_fn=lambda: now_halt)
        for _ in range(3):
            await dp_halt.record_api_failure()

        # 30분 + 1초 후
        now_after = now_halt + timedelta(minutes=30, seconds=1)
        dp_after = ExchangeDisconnectProtection(store, _config(), now_fn=lambda: now_after)
        result = await dp_after.check()
        assert result.allowed is True

    async def test_api_success_resets_failure_counter(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        await dp.record_api_failure()
        await dp.record_api_failure()
        await dp.record_api_success()
        # 리셋 후 다시 2번 실패해도 중단 안 됨
        await dp.record_api_failure()
        result = await dp.record_api_failure()
        assert result.allowed is True  # 2/3, 아직 중단 안 됨

    async def test_api_success_during_halt_does_not_reset(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        for _ in range(3):
            await dp.record_api_failure()
        # 중단 중 성공 호출
        await dp.record_api_success()
        result = await dp.check()
        assert result.allowed is False  # 여전히 중단 중

    async def test_failure_during_halt_does_not_increment_counter(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        for _ in range(3):
            await dp.record_api_failure()
        result = await dp.record_api_failure()  # 중단 중 추가 실패
        assert result.allowed is False
        assert result.halt_reason == HaltReason.CONSECUTIVE_API_FAILURES

    async def test_message_includes_remaining_minutes(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now)
        for _ in range(3):
            await dp.record_api_failure()
        result = await dp.check()
        assert "분" in result.message

    async def test_custom_threshold_two_failures_triggers_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        dp = _make(now, _config(threshold=2))
        await dp.record_api_failure()
        result = await dp.record_api_failure()
        assert result.allowed is False

    async def test_success_after_halt_expiry_fully_resets(self) -> None:
        now_halt = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        store = InMemorySafetyStateStore()
        dp_halt = ExchangeDisconnectProtection(store, _config(), now_fn=lambda: now_halt)
        for _ in range(3):
            await dp_halt.record_api_failure()

        now_after = now_halt + timedelta(minutes=31)
        dp_after = ExchangeDisconnectProtection(store, _config(), now_fn=lambda: now_after)
        await dp_after.record_api_success()
        state = await store.get_disconnect_state()
        assert state.consecutive_failures == 0
        assert not state.is_halted
