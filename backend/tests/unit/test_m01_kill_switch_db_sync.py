"""
M-01 단위 테스트 — Kill switch 발동 시 UserSettings.is_trading_active DB 동기화.

검증 항목:
  1. disable_auto_trading() — is_trading_active=True → UPDATE + WARNING 로그
  2. disable_auto_trading() — 이미 False → no-op (rowcount=0, 로그 없음)
  3. disable_auto_trading() — 잘못된 UUID → ValueError
  4. SafetyGateAdapter.on_trade_executed() — allowed=False → disable_auto_trading 호출
  5. SafetyGateAdapter.on_trade_executed() — 모든 allowed=True → disable_auto_trading 미호출
  6. SafetyGateAdapter.on_trade_executed() — 빈 결과 → disable_auto_trading 미호출
  7. Daily kill switch 발동 → DAILY_LOSS_LIMIT reason으로 adapter warning 로그
  8. Weekly kill switch 발동 → WEEKLY_LOSS_LIMIT reason으로 adapter warning 로그
  9. get_auto_trading_users() — 쿼리에 is_trading_active 필터 포함 확인
  10. disable_auto_trading DB commit 확인
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.orchestrator.models import PostTradeEvent
from app.safety.types import AlertLevel, HaltReason, SafetyCheckResult


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

def _event(user_id: str | None = None, max_loss: float = 100.0) -> PostTradeEvent:
    return PostTradeEvent(
        user_id=user_id or str(uuid.uuid4()),
        coin="BTC",
        direction="LONG",
        entry_price=Decimal("50000"),
        quantity=Decimal("0.002"),
        stop_loss=Decimal("48000"),
        max_loss_usdt=max_loss,
        period_start_balance=10000.0,
        week_start_balance=10000.0,
        current_balance=9900.0,
    )


def _check(allowed: bool, halt_reason: HaltReason | None = None) -> SafetyCheckResult:
    return SafetyCheckResult(
        allowed=allowed,
        halt_reason=halt_reason,
        message="test-message",
        alert_level=AlertLevel.CRITICAL if not allowed else AlertLevel.INFO,
    )


def _mock_session(rowcount: int = 1):
    """AsyncSessionLocal context manager mock."""
    mock_result = MagicMock()
    mock_result.rowcount = rowcount

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.commit  = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=None)
    return session, mock_result


# ── Group 1: disable_auto_trading() 단위 테스트 ──────────────────────────────

@pytest.mark.asyncio
async def test_disable_auto_trading_updates_when_active(caplog):
    """is_trading_active=True → UPDATE 실행, WARNING 로그 출력."""
    import logging
    from app.services.user_service import disable_auto_trading

    session, _ = _mock_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        with caplog.at_level(logging.WARNING, logger="app.services.user_service"):
            await disable_auto_trading(
                "00000000-0000-0000-0000-000000000001",
                reason="DAILY_LOSS_LIMIT",
            )

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert "auto_trading_disabled" in caplog.text
    assert "DAILY_LOSS_LIMIT" in caplog.text


@pytest.mark.asyncio
async def test_disable_auto_trading_noop_when_already_false(caplog):
    """rowcount=0 (이미 False) → DB commit은 하되 WARNING 로그 없음."""
    import logging
    from app.services.user_service import disable_auto_trading

    session, _ = _mock_session(rowcount=0)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        with caplog.at_level(logging.WARNING, logger="app.services.user_service"):
            await disable_auto_trading("00000000-0000-0000-0000-000000000002")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert "auto_trading_disabled" not in caplog.text


@pytest.mark.asyncio
async def test_disable_auto_trading_raises_on_invalid_uuid():
    """잘못된 UUID 문자열 → ValueError."""
    from app.services.user_service import disable_auto_trading

    with pytest.raises(ValueError):
        await disable_auto_trading("not-a-valid-uuid")


@pytest.mark.asyncio
async def test_disable_auto_trading_commits_to_db():
    """session.commit() 반드시 호출 확인."""
    from app.services.user_service import disable_auto_trading

    session, _ = _mock_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await disable_auto_trading("00000000-0000-0000-0000-000000000003")

    session.commit.assert_awaited_once()


# ── Group 2: SafetyGateAdapter kill switch DB 동기화 ─────────────────────────

@pytest.mark.asyncio
async def test_adapter_calls_disable_when_kill_switch_triggers():
    """on_trade_closed 결과에 allowed=False → disable_auto_trading 호출."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[
        _check(allowed=False, halt_reason=HaltReason.DAILY_LOSS_LIMIT),
    ])

    adapter = SafetyGateAdapter(mock_gate)
    session, _ = _mock_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(_event(user_id="00000000-0000-0000-0000-000000000010"))

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_adapter_skips_disable_when_all_allowed():
    """모든 결과 allowed=True → disable_auto_trading 미호출."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[
        _check(allowed=True),
        _check(allowed=True),
    ])

    adapter = SafetyGateAdapter(mock_gate)
    session, _ = _mock_session()
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(_event())

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_adapter_skips_disable_on_empty_results():
    """on_trade_closed 빈 결과 → disable_auto_trading 미호출."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[])

    adapter = SafetyGateAdapter(mock_gate)
    session, _ = _mock_session()
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(_event())

    session.execute.assert_not_awaited()


# ── Group 3: Kill switch 종류별 Warning 로그 검증 ─────────────────────────────

@pytest.mark.asyncio
async def test_daily_kill_switch_logs_warning(caplog):
    """Daily kill switch 발동 → adapter에서 DAILY_LOSS_LIMIT warning."""
    import logging
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[
        _check(allowed=False, halt_reason=HaltReason.DAILY_LOSS_LIMIT),
    ])

    adapter = SafetyGateAdapter(mock_gate)
    session, _ = _mock_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        with caplog.at_level(logging.WARNING, logger="app.safety.adapter"):
            await adapter.on_trade_executed(
                _event(user_id="00000000-0000-0000-0000-000000000020")
            )

    assert "kill_switch_triggered" in caplog.text
    assert "DAILY_LOSS_LIMIT" in caplog.text


@pytest.mark.asyncio
async def test_weekly_kill_switch_logs_warning(caplog):
    """Weekly kill switch 발동 → adapter에서 WEEKLY_LOSS_LIMIT warning."""
    import logging
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[
        _check(allowed=False, halt_reason=HaltReason.WEEKLY_LOSS_LIMIT),
    ])

    adapter = SafetyGateAdapter(mock_gate)
    session, _ = _mock_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        with caplog.at_level(logging.WARNING, logger="app.safety.adapter"):
            await adapter.on_trade_executed(
                _event(user_id="00000000-0000-0000-0000-000000000021")
            )

    assert "WEEKLY_LOSS_LIMIT" in caplog.text


@pytest.mark.asyncio
async def test_drawdown_protection_triggers_db_update():
    """Drawdown protection 발동 → disable_auto_trading 호출."""
    from app.safety.adapter import SafetyGateAdapter

    mock_gate = AsyncMock()
    mock_gate.on_trade_closed = AsyncMock(return_value=[
        _check(allowed=False, halt_reason=HaltReason.DRAWDOWN_PROTECTION),
    ])

    adapter = SafetyGateAdapter(mock_gate)
    session, _ = _mock_session(rowcount=1)
    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        await adapter.on_trade_executed(_event())

    session.execute.assert_awaited_once()


# ── Group 4: get_auto_trading_users 쿼리 로직 검증 ───────────────────────────

@pytest.mark.asyncio
async def test_get_auto_trading_users_query_filters_active():
    """get_auto_trading_users() 쿼리에 is_trading_active 필터 포함."""
    from app.services.user_service import get_auto_trading_users

    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=[])
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalars)

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_execute_result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=None)

    with patch("app.services.user_service.AsyncSessionLocal", return_value=session):
        users = await get_auto_trading_users()

    assert users == []
    # 쿼리가 실행됐으면 is_trading_active 필터가 포함된 SELECT
    session.execute.assert_awaited_once()
    stmt = session.execute.call_args[0][0]
    stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "is_trading_active" in stmt_str.lower()
