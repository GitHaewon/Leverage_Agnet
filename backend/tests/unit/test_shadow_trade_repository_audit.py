from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from agents.shadow.models import ShadowTradeRecord
from agents.shadow.risk_state import UnresolvedOpenRiskError
from app.repositories.shadow_trade_repository import ShadowTradeRepository


def _execute_result(*, rows=None, scalar=None):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows or []
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = scalar
    return result


@pytest.mark.asyncio
async def test_all_open_strategies_are_summed_for_portfolio_risk():
    baseline = MagicMock(actual_max_loss_usdt=Decimal("20"), id=uuid.uuid4())
    fast = MagicMock(actual_max_loss_usdt=Decimal("30"), id=uuid.uuid4())
    session = AsyncMock()
    session.execute.return_value = _execute_result(rows=[baseline, fast])

    risk = await ShadowTradeRepository(session).get_open_risk_usdt("u1")

    assert risk == Decimal("50")


@pytest.mark.asyncio
async def test_null_open_actual_max_loss_fails_closed():
    unresolved = MagicMock(actual_max_loss_usdt=None, id=uuid.uuid4())
    session = AsyncMock()
    session.execute.return_value = _execute_result(rows=[unresolved])

    with pytest.raises(UnresolvedOpenRiskError, match="OPEN_RISK_UNRESOLVED"):
        await ShadowTradeRepository(session).get_open_risk_usdt("u1")


def _record(strategy: str) -> ShadowTradeRecord:
    return ShadowTradeRecord.open(
        user_id="u1",
        coin="BTC",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("51000"),
        sl_price=Decimal("49500"),
        quantity=Decimal("0.01"),
        leverage=2,
        signal_id="11111111-1111-1111-1111-111111111111",
        strategy_version=strategy,
        actual_max_loss_usdt=Decimal("10"),
    )


@pytest.mark.asyncio
async def test_worker_retry_duplicate_is_idempotent():
    session = AsyncMock()
    session.execute.side_effect = [
        _execute_result(scalar=uuid.uuid4()),
        _execute_result(scalar=None),
    ]
    repo = ShadowTradeRepository(session)
    record = _record("baseline_v1")

    assert await repo.save(record) is True
    assert await repo.save(record) is False
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_same_signal_baseline_and_fast_are_independently_allowed():
    session = AsyncMock()
    session.execute.side_effect = [
        _execute_result(scalar=uuid.uuid4()),
        _execute_result(scalar=uuid.uuid4()),
    ]
    repo = ShadowTradeRepository(session)

    assert await repo.save(_record("baseline_v1")) is True
    assert await repo.save(_record("fast_exit_v2")) is True


@pytest.mark.asyncio
async def test_null_strategy_is_normalized_before_insert():
    session = AsyncMock()
    session.execute.return_value = _execute_result(scalar=uuid.uuid4())
    record = _record("baseline_v1")
    record.strategy_version = None

    assert await ShadowTradeRepository(session).save(record) is True
    statement = session.execute.await_args.args[0]
    assert "legacy_unknown" in str(statement.compile().params.values())


@pytest.mark.asyncio
async def test_missing_signal_id_is_rejected_before_insert():
    session = AsyncMock()
    record = _record("baseline_v1")
    record.signal_id = None

    with pytest.raises(ValueError, match="signal_id"):
        await ShadowTradeRepository(session).save(record)
    session.execute.assert_not_awaited()
