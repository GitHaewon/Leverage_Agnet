"""
드로우다운 보호 단위 테스트 (12 tests).

검증 대상:
  - DrawdownProtection:
      초기 고점 설정, 고점 갱신, 경고 알림, 중단 발동,
      check() 상태 확인, resume() 수동 재활성화
"""
from __future__ import annotations

import pytest

from app.safety.drawdown import DrawdownProtection
from app.safety.state import InMemorySafetyStateStore
from app.safety.types import HaltReason, SafetyConfig

USER = "user-001"


def _make(warning_pct: float = 0.10, halt_pct: float = 0.20) -> DrawdownProtection:
    config = SafetyConfig(
        live_trading_enabled=True,
        drawdown_warning_pct=warning_pct,
        drawdown_halt_pct=halt_pct,
    )
    return DrawdownProtection(InMemorySafetyStateStore(), config)


class TestDrawdownProtection:

    async def test_initial_balance_sets_peak(self) -> None:
        dp = _make()
        result = await dp.update_balance(USER, 10_000.0)
        assert result.allowed is True

    async def test_balance_rise_updates_peak(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        result = await dp.update_balance(USER, 11_000.0)
        assert result.allowed is True
        state = await dp._store.get_drawdown_state(USER)
        assert state.peak_balance == 11_000.0

    async def test_small_drawdown_below_warning_returns_allowed(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        result = await dp.update_balance(USER, 9_500.0)  # -5%, 경고 기준 10% 미만
        assert result.allowed is True
        assert result.halt_reason is None

    async def test_drawdown_at_warning_threshold_returns_warning(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        result = await dp.update_balance(USER, 9_000.0)  # -10%
        assert result.allowed is True
        assert "경고" in result.message

    async def test_warning_sent_only_once(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        r1 = await dp.update_balance(USER, 9_000.0)   # -10%, 경고 발송
        r2 = await dp.update_balance(USER, 8_900.0)   # -11%, 경고 중복 발송 없음
        assert "경고" in r1.message
        assert "경고" not in r2.message or r2.alert_level.value == "info"

    async def test_drawdown_at_halt_threshold_triggers_protection(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        result = await dp.update_balance(USER, 8_000.0)  # -20%
        assert result.allowed is False
        assert result.halt_reason == HaltReason.DRAWDOWN_PROTECTION

    async def test_drawdown_exceeding_halt_threshold_triggers_protection(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        result = await dp.update_balance(USER, 7_000.0)  # -30%
        assert result.allowed is False

    async def test_check_returns_blocked_when_halted(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        await dp.update_balance(USER, 8_000.0)  # 중단 발동
        result = await dp.check(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.DRAWDOWN_PROTECTION

    async def test_check_returns_allowed_when_not_halted(self) -> None:
        dp = _make()
        result = await dp.check(USER)
        assert result.allowed is True

    async def test_resume_clears_halt(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        await dp.update_balance(USER, 8_000.0)  # 중단 발동
        await dp.resume(USER)
        result = await dp.check(USER)
        assert result.allowed is True

    async def test_resume_resets_peak_to_current_balance(self) -> None:
        dp = _make()
        await dp.update_balance(USER, 10_000.0)
        await dp.update_balance(USER, 8_000.0)  # 중단 발동
        await dp.resume(USER)
        state = await dp._store.get_drawdown_state(USER)
        # 재개 후 고점은 현재 잔고($8,000)로 리셋되어야 한다
        assert state.peak_balance == 8_000.0

    async def test_different_users_are_independent(self) -> None:
        store = InMemorySafetyStateStore()
        config = SafetyConfig(drawdown_halt_pct=0.20)
        dp = DrawdownProtection(store, config)

        await dp.update_balance("user-A", 10_000.0)
        await dp.update_balance("user-A", 8_000.0)  # A는 중단

        result_b = await dp.check("user-B")
        assert result_b.allowed is True
