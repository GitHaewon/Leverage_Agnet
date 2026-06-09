"""
Safety Gate 통합 단위 테스트 (18 tests).

검증 대상:
  - SafetyGate.check_order_allowed():
      마스터 스위치, 긴급 중단, 연결 오류, 일일 킬스위치, 주간 킬스위치, 드로우다운
  - SafetyGate.on_trade_closed():
      손실/이익 거래 처리, 킬스위치/드로우다운 연동
  - SafetyGate.on_api_failure() / on_api_success()
  - SafetyGate 편의 메서드: trigger_emergency, deactivate_emergency,
    resume_drawdown, reset_daily_switch, reset_weekly_switch
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.safety.gate import SafetyGate
from app.safety.state import InMemorySafetyStateStore
from app.safety.types import HaltReason, SafetyConfig

UTC = timezone.utc
USER = "user-001"

FIXED_NOW = datetime(2025, 6, 9, 12, 0, tzinfo=UTC)


def _make_gate(
    live: bool = True,
    daily_pct: float = 0.03,
    weekly_pct: float = 0.10,
    drawdown_halt: float = 0.20,
    threshold: int = 3,
    now: datetime | None = None,
) -> SafetyGate:
    config = SafetyConfig(
        live_trading_enabled=live,
        daily_loss_limit_pct=daily_pct,
        weekly_loss_limit_pct=weekly_pct,
        drawdown_halt_pct=drawdown_halt,
        api_failure_halt_threshold=threshold,
    )
    return SafetyGate(
        InMemorySafetyStateStore(),
        config,
        now_fn=lambda: (now or FIXED_NOW),
    )


class TestSafetyGateCheckOrderAllowed:

    async def test_all_clear_returns_allowed(self) -> None:
        gate = _make_gate()
        result = await gate.check_order_allowed(USER)
        assert result.allowed is True

    async def test_live_trading_disabled_blocks_all(self) -> None:
        gate = _make_gate(live=False)
        result = await gate.check_order_allowed(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.LIVE_TRADING_DISABLED

    async def test_emergency_shutdown_blocks_order(self) -> None:
        gate = _make_gate()
        await gate.trigger_emergency("시스템 오류", activated_by="system")
        result = await gate.check_order_allowed(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.EMERGENCY_SHUTDOWN

    async def test_exchange_disconnect_blocks_order(self) -> None:
        gate = _make_gate(threshold=3)
        for _ in range(3):
            await gate.on_api_failure()
        result = await gate.check_order_allowed(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.CONSECUTIVE_API_FAILURES

    async def test_daily_kill_switch_blocks_order(self) -> None:
        gate = _make_gate(daily_pct=0.03)
        # 한도 $300 = 3% of $10,000
        await gate._daily_ks.record_loss(USER, 300.0, 10_000.0)
        result = await gate.check_order_allowed(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.DAILY_LOSS_LIMIT

    async def test_weekly_kill_switch_blocks_order(self) -> None:
        gate = _make_gate(weekly_pct=0.10)
        # 한도 $1,000 = 10% of $10,000
        await gate._weekly_ks.record_loss(USER, 1_000.0, 10_000.0)
        result = await gate.check_order_allowed(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.WEEKLY_LOSS_LIMIT

    async def test_drawdown_protection_blocks_order(self) -> None:
        gate = _make_gate(drawdown_halt=0.20)
        await gate._drawdown.update_balance(USER, 10_000.0)
        await gate._drawdown.update_balance(USER, 8_000.0)  # -20%
        result = await gate.check_order_allowed(USER)
        assert result.allowed is False
        assert result.halt_reason == HaltReason.DRAWDOWN_PROTECTION

    async def test_check_order_short_circuits_at_first_failure(self) -> None:
        gate = _make_gate(live=False)
        # live=False이면 나머지 검증은 수행되지 않는다
        await gate.trigger_emergency("오류")
        result = await gate.check_order_allowed(USER)
        # 반드시 LIVE_TRADING_DISABLED가 먼저 반환되어야 함
        assert result.halt_reason == HaltReason.LIVE_TRADING_DISABLED


class TestSafetyGateOnTradeClosed:

    async def test_profit_trade_only_updates_drawdown(self) -> None:
        gate = _make_gate()
        results = await gate.on_trade_closed(
            USER,
            pnl_usdt=500.0,           # 수익
            period_start_balance=10_000.0,
            week_start_balance=10_000.0,
            current_balance=10_500.0,
        )
        # 수익 거래는 킬스위치 손실 기록 없이 드로우다운만 업데이트
        assert any(r.allowed for r in results)

    async def test_loss_trade_triggers_daily_kill_switch(self) -> None:
        gate = _make_gate(daily_pct=0.03)
        results = await gate.on_trade_closed(
            USER,
            pnl_usdt=-300.0,          # 일일 한도 전액 손실
            period_start_balance=10_000.0,
            week_start_balance=10_000.0,
            current_balance=9_700.0,
        )
        blocked = [r for r in results if not r.allowed]
        assert any(r.halt_reason == HaltReason.DAILY_LOSS_LIMIT for r in blocked)

    async def test_loss_trade_triggers_weekly_kill_switch(self) -> None:
        gate = _make_gate(weekly_pct=0.10)
        results = await gate.on_trade_closed(
            USER,
            pnl_usdt=-1_000.0,
            period_start_balance=10_000.0,
            week_start_balance=10_000.0,
            current_balance=9_000.0,
        )
        blocked = [r for r in results if not r.allowed]
        assert any(r.halt_reason == HaltReason.WEEKLY_LOSS_LIMIT for r in blocked)

    async def test_drawdown_triggered_by_large_loss(self) -> None:
        gate = _make_gate(drawdown_halt=0.20)
        await gate._drawdown.update_balance(USER, 10_000.0)  # 고점 설정
        results = await gate.on_trade_closed(
            USER,
            pnl_usdt=-2_000.0,
            period_start_balance=10_000.0,
            week_start_balance=10_000.0,
            current_balance=8_000.0,   # -20% 드로우다운
        )
        blocked = [r for r in results if not r.allowed]
        assert any(r.halt_reason == HaltReason.DRAWDOWN_PROTECTION for r in blocked)

    async def test_zero_loss_does_not_trigger_kill_switch(self) -> None:
        gate = _make_gate()
        await gate._drawdown.update_balance(USER, 10_000.0)
        results = await gate.on_trade_closed(
            USER,
            pnl_usdt=0.0,
            period_start_balance=10_000.0,
            week_start_balance=10_000.0,
            current_balance=10_000.0,
        )
        # 0 손실이면 킬스위치 업데이트 없음 (드로우다운만)
        assert len(results) == 1


class TestSafetyGateConvenienceMethods:

    async def test_trigger_and_deactivate_emergency(self) -> None:
        gate = _make_gate()
        await gate.trigger_emergency("테스트")
        r1 = await gate.check_order_allowed(USER)
        assert r1.allowed is False

        await gate.deactivate_emergency()
        r2 = await gate.check_order_allowed(USER)
        assert r2.allowed is True

    async def test_resume_drawdown_clears_protection(self) -> None:
        gate = _make_gate(drawdown_halt=0.20)
        await gate._drawdown.update_balance(USER, 10_000.0)
        await gate._drawdown.update_balance(USER, 8_000.0)

        r1 = await gate.check_order_allowed(USER)
        assert r1.allowed is False

        await gate.resume_drawdown(USER)
        r2 = await gate.check_order_allowed(USER)
        assert r2.allowed is True

    async def test_reset_daily_switch_clears_halt(self) -> None:
        gate = _make_gate(daily_pct=0.03)
        await gate._daily_ks.record_loss(USER, 300.0, 10_000.0)
        await gate.reset_daily_switch(USER)
        result = await gate.check_order_allowed(USER)
        assert result.allowed is True

    async def test_reset_weekly_switch_clears_halt(self) -> None:
        gate = _make_gate(weekly_pct=0.10)
        await gate._weekly_ks.record_loss(USER, 1_000.0, 10_000.0)
        await gate.reset_weekly_switch(USER)
        result = await gate.check_order_allowed(USER)
        assert result.allowed is True

    async def test_api_success_resets_disconnect_counter(self) -> None:
        gate = _make_gate(threshold=3)
        await gate.on_api_failure()
        await gate.on_api_failure()
        await gate.on_api_success()
        # 리셋 후 2번 더 실패해도 중단 안 됨 (누적 2/3)
        await gate.on_api_failure()
        result = await gate.on_api_failure()
        assert result.allowed is True
