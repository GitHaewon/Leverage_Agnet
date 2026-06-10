"""
H-05 단위 테스트 — POST /trading/resume (자동매매 재개)

검증 항목:
  1.  SafetyGate.get_halt_status() — 미중단 → is_halted=False
  2.  SafetyGate.get_halt_status() — 일일 Kill switch 중단 → DAILY_LOSS_LIMIT
  3.  SafetyGate.get_halt_status() — 주간 Kill switch 중단 → WEEKLY_LOSS_LIMIT
  4.  SafetyGate.get_halt_status() — 중단 기간 만료 → is_halted=False
  5.  enable_auto_trading() — is_trading_active=False → UPDATE + INFO 로그
  6.  enable_auto_trading() — 이미 True → no-op (rowcount=0)
  7.  resume_auto_trading() — 중단 활성 → ConflictError(TRADING_001)
  8.  resume_auto_trading() — 중단 만료 → reset_daily + reset_weekly + enable DB 호출
  9.  resume_auto_trading() — 미중단 상태 → 정상 재개 (dict 반환)
  10. resume_auto_trading() — 일일 halt_reason 포함 detail 검증
  11. resume_auto_trading() — 주간 halt_until 포함 detail 검증
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.safety import InMemorySafetyStateStore, SafetyConfig, SafetyGate
from app.safety.types import HaltReason, KillSwitchState, UserHaltStatus
from app.utils.exceptions import ConflictError


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

def _future(seconds: int = 3600) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds: int = 3600) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _mock_db_session(rowcount: int = 1):
    mock_result = MagicMock()
    mock_result.rowcount = rowcount
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.commit  = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=None)
    return session


# ── Group 1: SafetyGate.get_halt_status() ────────────────────────────────────

@pytest.mark.asyncio
async def test_get_halt_status_not_halted():
    """미중단 상태 → is_halted=False."""
    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    status = await gate.get_halt_status(user_id)
    assert status.is_halted is False
    assert status.halt_reason is None
    assert status.halt_until is None


@pytest.mark.asyncio
async def test_get_halt_status_daily_halted():
    """일일 Kill switch 활성 → DAILY_LOSS_LIMIT 반환."""
    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    # 일일 kill switch 수동 설정
    daily_state = KillSwitchState(
        user_id=user_id,
        is_halted=True,
        halt_reason=HaltReason.DAILY_LOSS_LIMIT,
        halt_until=_future(),
    )
    await store.set_daily_kill_switch(user_id, daily_state)

    status = await gate.get_halt_status(user_id)
    assert status.is_halted is True
    assert status.halt_reason == HaltReason.DAILY_LOSS_LIMIT
    assert status.halt_until is not None


@pytest.mark.asyncio
async def test_get_halt_status_weekly_halted():
    """주간 Kill switch 활성 → WEEKLY_LOSS_LIMIT 반환."""
    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    weekly_state = KillSwitchState(
        user_id=user_id,
        is_halted=True,
        halt_reason=HaltReason.WEEKLY_LOSS_LIMIT,
        halt_until=_future(7 * 86400),
    )
    await store.set_weekly_kill_switch(user_id, weekly_state)

    status = await gate.get_halt_status(user_id)
    assert status.is_halted is True
    assert status.halt_reason == HaltReason.WEEKLY_LOSS_LIMIT


@pytest.mark.asyncio
async def test_get_halt_status_expired_halt():
    """중단 기간 만료 (halt_until < now) → is_halted=False."""
    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    # halt_until이 과거인 상태 (이미 만료)
    expired_state = KillSwitchState(
        user_id=user_id,
        is_halted=True,
        halt_reason=HaltReason.DAILY_LOSS_LIMIT,
        halt_until=_past(60),   # 1분 전에 만료
    )
    await store.set_daily_kill_switch(user_id, expired_state)

    status = await gate.get_halt_status(user_id)
    assert status.is_halted is False


# ── Group 2: enable_auto_trading() ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_enable_auto_trading_updates_db(caplog):
    """is_trading_active=False → UPDATE + INFO 로그."""
    import logging
    from app.services.user_service import enable_auto_trading

    session = _mock_db_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        with caplog.at_level(logging.INFO, logger="app.services.user_service"):
            await enable_auto_trading("00000000-0000-0000-0000-000000000001")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert "auto_trading_enabled" in caplog.text


@pytest.mark.asyncio
async def test_enable_auto_trading_noop_when_already_true(caplog):
    """이미 True (rowcount=0) → commit은 하되 INFO 로그 없음."""
    import logging
    from app.services.user_service import enable_auto_trading

    session = _mock_db_session(rowcount=0)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        with caplog.at_level(logging.INFO, logger="app.services.user_service"):
            await enable_auto_trading("00000000-0000-0000-0000-000000000002")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert "auto_trading_enabled" not in caplog.text


# ── Group 3: resume_auto_trading() 서비스 ────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_raises_conflict_when_halted():
    """Kill switch 중단 활성 → ConflictError(TRADING_001)."""
    from app.services.trading_service import resume_auto_trading

    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    await store.set_daily_kill_switch(
        user_id,
        KillSwitchState(
            user_id=user_id,
            is_halted=True,
            halt_reason=HaltReason.DAILY_LOSS_LIMIT,
            halt_until=_future(),
        ),
    )

    with pytest.raises(ConflictError) as exc_info:
        await resume_auto_trading(user_id, gate)

    assert exc_info.value.code == "TRADING_001"
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_resume_calls_reset_and_enable_when_not_halted():
    """미중단 상태 → reset_daily + reset_weekly + enable DB 호출."""
    from app.services.trading_service import resume_auto_trading

    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    session = _mock_db_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        result = await resume_auto_trading(user_id, gate)

    assert result["is_trading_active"] is True
    assert "resumed_at" in result
    session.execute.assert_awaited_once()  # enable_auto_trading DB 호출


@pytest.mark.asyncio
async def test_resume_succeeds_after_halt_expired():
    """중단 기간 만료 후 재개 → 정상 처리."""
    from app.services.trading_service import resume_auto_trading

    store = InMemorySafetyStateStore()
    gate  = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    # 이미 만료된 halt 상태 설정
    await store.set_daily_kill_switch(
        user_id,
        KillSwitchState(
            user_id=user_id,
            is_halted=True,
            halt_reason=HaltReason.DAILY_LOSS_LIMIT,
            halt_until=_past(60),
        ),
    )

    session = _mock_db_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        result = await resume_auto_trading(user_id, gate)

    assert result["is_trading_active"] is True


@pytest.mark.asyncio
async def test_resume_conflict_includes_daily_halt_detail():
    """일일 Kill switch → ConflictError detail에 halt_reason + halt_until 포함."""
    from app.services.trading_service import resume_auto_trading

    store   = InMemorySafetyStateStore()
    gate    = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())
    halt_at = _future(3600)

    await store.set_daily_kill_switch(
        user_id,
        KillSwitchState(
            user_id=user_id,
            is_halted=True,
            halt_reason=HaltReason.DAILY_LOSS_LIMIT,
            halt_until=halt_at,
        ),
    )

    with pytest.raises(ConflictError) as exc_info:
        await resume_auto_trading(user_id, gate)

    detail = exc_info.value.detail
    assert detail["halt_reason"] == "DAILY_LOSS_LIMIT"
    assert detail["halt_until"] is not None


@pytest.mark.asyncio
async def test_resume_conflict_includes_weekly_halt_detail():
    """주간 Kill switch → ConflictError detail에 WEEKLY_LOSS_LIMIT 포함."""
    from app.services.trading_service import resume_auto_trading

    store   = InMemorySafetyStateStore()
    gate    = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    await store.set_weekly_kill_switch(
        user_id,
        KillSwitchState(
            user_id=user_id,
            is_halted=True,
            halt_reason=HaltReason.WEEKLY_LOSS_LIMIT,
            halt_until=_future(7 * 86400),
        ),
    )

    with pytest.raises(ConflictError) as exc_info:
        await resume_auto_trading(user_id, gate)

    detail = exc_info.value.detail
    assert detail["halt_reason"] == "WEEKLY_LOSS_LIMIT"


@pytest.mark.asyncio
async def test_resume_resets_both_kill_switches():
    """재개 후 daily/weekly kill switch가 초기화된다."""
    from app.services.trading_service import resume_auto_trading

    store   = InMemorySafetyStateStore()
    gate    = SafetyGate(store=store, config=SafetyConfig(live_trading_enabled=True))
    user_id = str(uuid.uuid4())

    # 둘 다 만료된 halt 설정
    expired = KillSwitchState(
        user_id=user_id,
        is_halted=True,
        halt_reason=HaltReason.DAILY_LOSS_LIMIT,
        halt_until=_past(60),
    )
    await store.set_daily_kill_switch(user_id, expired)
    await store.set_weekly_kill_switch(user_id, expired)

    session = _mock_db_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await resume_auto_trading(user_id, gate)

    # 리셋 후 상태 확인
    daily_state  = await store.get_daily_kill_switch(user_id)
    weekly_state = await store.get_weekly_kill_switch(user_id)
    assert daily_state.is_halted is False
    assert weekly_state.is_halted is False
