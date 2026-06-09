"""
일일/주간 킬스위치 단위 테스트 (22 tests).

검증 대상:
  - DailyKillSwitch:  손실 누적, 단계별 경고, 한도 발동, 자동 리셋
  - WeeklyKillSwitch: 손실 누적, 단계별 경고, 한도 발동, 월요일 자동 리셋
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.safety.kill_switch import DailyKillSwitch, WeeklyKillSwitch
from app.safety.state import InMemorySafetyStateStore
from app.safety.types import HaltReason, SafetyConfig

UTC = timezone.utc
USER = "user-001"


def _config(daily_pct: float = 0.03, weekly_pct: float = 0.10) -> SafetyConfig:
    return SafetyConfig(
        live_trading_enabled=True,
        daily_loss_limit_pct=daily_pct,
        weekly_loss_limit_pct=weekly_pct,
    )


def _fixed_now(dt: datetime):
    return lambda: dt


# ── TestDailyKillSwitch ───────────────────────────────────────────────────────

class TestDailyKillSwitch:

    def _make(self, now: datetime, config: SafetyConfig | None = None) -> DailyKillSwitch:
        return DailyKillSwitch(
            InMemorySafetyStateStore(), config or _config(), now_fn=_fixed_now(now)
        )

    async def test_no_loss_check_returns_allowed(self) -> None:
        ks = self._make(datetime(2025, 6, 9, 12, 0, tzinfo=UTC))
        result = await ks.check(USER)
        assert result.allowed is True

    async def test_small_loss_under_warning_returns_allowed(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 3% 한도 × $10,000 = $300. 손실 $100 = 33% → 경고 기준 50% 미만
        result = await ks.record_loss(USER, 100.0, 10_000.0)
        assert result.allowed is True
        assert result.halt_reason is None

    async def test_loss_at_warning_threshold_returns_warning(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 한도 $300, 50% = $150
        result = await ks.record_loss(USER, 150.0, 10_000.0)
        assert result.allowed is True
        assert "경고" in result.message

    async def test_loss_at_caution_threshold_returns_caution(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 한도 $300, 80% = $240
        result = await ks.record_loss(USER, 240.0, 10_000.0)
        assert result.allowed is True
        assert "주의" in result.message

    async def test_loss_at_halt_threshold_triggers_kill_switch(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 한도 $300, 100% = $300
        result = await ks.record_loss(USER, 300.0, 10_000.0)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.DAILY_LOSS_LIMIT

    async def test_loss_exceeding_halt_triggers_kill_switch(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 단일 대형 손실
        result = await ks.record_loss(USER, 500.0, 10_000.0)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.DAILY_LOSS_LIMIT

    async def test_cumulative_losses_trigger_kill_switch(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        await ks.record_loss(USER, 100.0, 10_000.0)
        await ks.record_loss(USER, 100.0, 10_000.0)
        result = await ks.record_loss(USER, 100.0, 10_000.0)  # 합계 $300 = 한도
        assert result.allowed is False

    async def test_check_returns_blocked_after_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        await ks.record_loss(USER, 300.0, 10_000.0)
        result = await ks.check(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.DAILY_LOSS_LIMIT

    async def test_check_auto_resets_after_midnight(self) -> None:
        before_midnight = datetime(2025, 6, 9, 23, 30, tzinfo=UTC)
        ks_halt = self._make(before_midnight)
        await ks_halt.record_loss(USER, 300.0, 10_000.0)

        # 자정 이후 시각으로 check
        after_midnight = datetime(2025, 6, 10, 0, 1, tzinfo=UTC)
        ks_reset = DailyKillSwitch(
            ks_halt._store, _config(), now_fn=_fixed_now(after_midnight)
        )
        result = await ks_reset.check(USER)
        assert result.allowed is True

    async def test_manual_reset_clears_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        await ks.record_loss(USER, 300.0, 10_000.0)
        await ks.reset(USER)
        result = await ks.check(USER)
        assert result.allowed is True

    async def test_different_users_are_independent(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        store = InMemorySafetyStateStore()
        ks = DailyKillSwitch(store, _config(), now_fn=_fixed_now(now))

        await ks.record_loss("user-A", 300.0, 10_000.0)
        result_b = await ks.check("user-B")
        assert result_b.allowed is True


# ── TestWeeklyKillSwitch ──────────────────────────────────────────────────────

class TestWeeklyKillSwitch:

    def _make(self, now: datetime, config: SafetyConfig | None = None) -> WeeklyKillSwitch:
        return WeeklyKillSwitch(
            InMemorySafetyStateStore(), config or _config(), now_fn=_fixed_now(now)
        )

    async def test_no_loss_check_returns_allowed(self) -> None:
        ks = self._make(datetime(2025, 6, 9, 12, 0, tzinfo=UTC))
        result = await ks.check(USER)
        assert result.allowed is True

    async def test_small_loss_under_warning_returns_allowed(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 10% 한도 × $10,000 = $1,000. 손실 $400 = 40% → 경고 기준 50% 미만
        result = await ks.record_loss(USER, 400.0, 10_000.0)
        assert result.allowed is True
        assert result.halt_reason is None

    async def test_loss_at_warning_threshold_returns_warning(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 한도 $1,000, 50% = $500
        result = await ks.record_loss(USER, 500.0, 10_000.0)
        assert result.allowed is True
        assert "경고" in result.message

    async def test_loss_at_caution_threshold_returns_caution(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        # 한도 $1,000, 75% = $750
        result = await ks.record_loss(USER, 750.0, 10_000.0)
        assert result.allowed is True
        assert "주의" in result.message

    async def test_loss_at_halt_threshold_triggers_kill_switch(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        result = await ks.record_loss(USER, 1_000.0, 10_000.0)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.WEEKLY_LOSS_LIMIT

    async def test_check_returns_blocked_after_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        await ks.record_loss(USER, 1_000.0, 10_000.0)
        result = await ks.check(USER)
        assert result.allowed is False

    async def test_check_auto_resets_after_next_monday(self) -> None:
        # 수요일 (weekday=2)
        wednesday = datetime(2025, 6, 11, 12, 0, tzinfo=UTC)
        ks_halt = self._make(wednesday)
        await ks_halt.record_loss(USER, 1_000.0, 10_000.0)

        # 다음 월요일 이후
        next_monday = datetime(2025, 6, 16, 0, 1, tzinfo=UTC)
        ks_reset = WeeklyKillSwitch(
            ks_halt._store, _config(), now_fn=_fixed_now(next_monday)
        )
        result = await ks_reset.check(USER)
        assert result.allowed is True

    async def test_manual_reset_clears_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        await ks.record_loss(USER, 1_000.0, 10_000.0)
        await ks.reset(USER)
        result = await ks.check(USER)
        assert result.allowed is True

    async def test_cumulative_losses_trigger_weekly_halt(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        await ks.record_loss(USER, 400.0, 10_000.0)
        await ks.record_loss(USER, 400.0, 10_000.0)
        result = await ks.record_loss(USER, 200.0, 10_000.0)  # 합계 $1,000
        assert result.allowed is False

    async def test_halt_message_mentions_monday(self) -> None:
        now = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)
        ks = self._make(now)
        result = await ks.record_loss(USER, 1_000.0, 10_000.0)
        assert "월요일" in result.message or "UTC" in result.message
