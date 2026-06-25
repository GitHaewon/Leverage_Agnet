"""
C-01 regression tests — ModuleNotFoundError must never recur.

These tests verify that analysis_worker.py and the two new service modules
import cleanly and expose the expected callables.
"""
from __future__ import annotations

import importlib
import sys
import uuid
from datetime import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Import smoke tests ───────────────────────────────────────────────────────


def test_analysis_worker_importable():
    """No ModuleNotFoundError on import."""
    sys.modules.pop("app.workers.analysis_worker", None)
    mod = importlib.import_module("app.workers.analysis_worker")
    assert callable(mod.run_analysis_cycle)
    assert callable(mod.run_signal_for_user)
    assert callable(mod.expire_signals)


def test_user_service_importable():
    sys.modules.pop("app.services.user_service", None)
    mod = importlib.import_module("app.services.user_service")
    assert callable(mod.get_auto_trading_users)
    assert callable(mod.get_user_context)


def test_signal_service_importable():
    sys.modules.pop("app.services.signal_service", None)
    mod = importlib.import_module("app.services.signal_service")
    assert callable(mod.expire_old_signals)


def test_market_data_agent_importable():
    sys.modules.pop("agents.market_data.agent", None)
    mod = importlib.import_module("agents.market_data.agent")
    assert hasattr(mod, "MarketDataAgent")


# ── Unit tests: expire_old_signals ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_expire_old_signals_returns_zero_when_nothing_to_expire():
    mock_result = MagicMock(rowcount=0)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    class _MockSession:
        async def __aenter__(self):
            return mock_db
        async def __aexit__(self, *_):
            pass

    with patch("app.services.signal_service.celery_session", _MockSession):
        from app.services.signal_service import expire_old_signals
        count = await expire_old_signals()

    assert count == 0
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_expire_old_signals_returns_rowcount():
    mock_result = MagicMock(rowcount=5)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    class _MockSession:
        async def __aenter__(self):
            return mock_db
        async def __aexit__(self, *_):
            pass

    with patch("app.services.signal_service.celery_session", _MockSession):
        from app.services.signal_service import expire_old_signals
        count = await expire_old_signals()

    assert count == 5


# ── Unit tests: get_auto_trading_users ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_auto_trading_users_empty_db_returns_empty_list():
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute = AsyncMock(return_value=mock_result)

    class _MockSession:
        async def __aenter__(self):
            return mock_db
        async def __aexit__(self, *_):
            pass

    with patch("app.services.user_service.celery_session", _MockSession):
        from app.services.user_service import get_auto_trading_users
        users = await get_auto_trading_users()

    assert users == []


@pytest.mark.asyncio
async def test_get_user_context_raises_for_missing_user():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    class _MockSession:
        async def __aenter__(self):
            return mock_db
        async def __aexit__(self, *_):
            pass

    with patch("app.services.user_service.celery_session", _MockSession):
        from app.services.user_service import get_user_context
        with pytest.raises(ValueError, match="not found"):
            await get_user_context(str(uuid.uuid4()))


# ── Unit test: UserTradingContext defaults ───────────────────────────────────


def test_user_trading_context_defaults():
    from app.services.user_service import UserTradingContext
    uid = uuid.uuid4()
    ctx = UserTradingContext(id=uid, plan="free")
    assert ctx.user_id == uid
    assert ctx.daily_loss_usdt == Decimal("0")
    assert ctx.weekly_limit_usdt == Decimal("500")
    assert ctx.consecutive_losses == 0
    assert ctx.open_positions == []
    assert ctx.risk_per_trade == 0.01
    assert ctx.max_leverage == 5
    assert ctx.is_trading_active is True


def test_user_trading_context_from_user_builds_shadow_accounts():
    from app.services.user_service import UserTradingContext

    uid = uuid.uuid4()
    user = SimpleNamespace(
        id=uid,
        plan="pro",
        risk_profile="moderate",
        settings=SimpleNamespace(
            risk_per_trade=Decimal("0.02"),
            max_leverage=7,
            max_concurrent_positions=2,
            daily_loss_limit=Decimal("250"),
            is_trading_active=True,
            allowed_hours_start=time(0, 0),
            allowed_hours_end=time(23, 59),
        ),
    )

    with patch(
        "app.services.user_service.app_settings.SHADOW_INITIAL_BALANCE_USDT",
        Decimal("10000"),
    ):
        ctx = UserTradingContext.from_user(user)

    assert ctx.user_id == uid
    assert ctx.account_state.available_balance == Decimal("10000")
    assert ctx.portfolio_account.available_balance == Decimal("10000")
    assert ctx.risk_per_trade == 0.02
    assert ctx.max_leverage == 7
    assert ctx.max_concurrent_positions == 2
    assert ctx.daily_loss_limit_pct == 0.025
    assert ctx.weekly_limit_usdt == Decimal("1250")
    assert ctx.allowed_hours_start == "00:00"
    assert ctx.allowed_hours_end == "23:59"


def test_user_trading_context_does_not_fake_live_account():
    from app.services.user_service import UserTradingContext

    user = SimpleNamespace(
        id=uuid.uuid4(),
        plan="pro",
        risk_profile="moderate",
        settings=None,
    )

    with (
        patch("app.services.user_service.app_settings.LIVE_TRADING_ENABLED", True),
        patch("app.services.user_service.app_settings.SHADOW_TRADING_ENABLED", False),
    ):
        ctx = UserTradingContext.from_user(user)

    assert ctx.account_state is None
    assert ctx.portfolio_account is None
