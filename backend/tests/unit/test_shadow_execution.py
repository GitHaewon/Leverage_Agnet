"""
Shadow Trading Mode 단위 테스트.

검증 항목:
  1.  Risk rejected → ExecutionResult(approved=False, executed=False)
  2.  Risk approved → store.save() 1회 호출
  3.  Risk approved → ExecutionResult(mode="paper", executed=True)
  4.  가상 FilledOrder의 price가 signal 가격과 일치
  5.  entry_order.exchange_order_id에 "shadow-entry-" 접두사 포함
  6.  store.save() 예외 → SYSTEM_ERROR 격리 (파이프라인 영향 없음)
  7.  ShadowTradeRecord.close() LONG TP_HIT — PnL = (exit - entry) * qty
  8.  ShadowTradeRecord.close() SHORT SL_HIT — PnL = (entry - exit) * qty
  9.  ShadowTradeRecord.close() LONG SL_HIT — 손실(음수 PnL)
  10. ShadowTradeRecord.close() Duration = closed_at - opened_at
  11. ShadowTradeRecord.open() — status 기본값 "OPEN"
  12. check_and_close_shadow_trades — LONG TP_HIT
  13. check_and_close_shadow_trades — SHORT SL_HIT
  14. check_and_close_shadow_trades — 가격 미도달 시 청산 안 함
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.execution.models import ExecutionRequest
from agents.shadow.execution import ShadowExecutionEngine
from agents.shadow.models import ShadowTradeRecord


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

def _signal(
    direction: str = "LONG",
    entry_price: str = "50000",
    tp_price: str = "55000",
    sl_price: str = "48000",
    coin: str = "BTC",
    symbol: str = "BTCUSDT",
) -> MagicMock:
    s = MagicMock()
    s.direction = direction
    s.entry_price = Decimal(entry_price)
    s.take_profit = Decimal(tp_price)
    s.stop_loss = Decimal(sl_price)
    s.coin = coin
    s.symbol = symbol
    return s


def _validation(approved: bool = True, qty: str = "0.01", leverage: int = 5) -> MagicMock:
    v = MagicMock()
    v.approved = approved
    v.quantity = Decimal(qty)
    v.final_leverage = leverage
    v.rejection_code = "RISK_FAIL" if not approved else None
    v.rejection_reason = "test rejection" if not approved else None
    v.warnings = []
    return v


def _user_ctx(user_id: str = "test-user-001") -> MagicMock:
    ctx = MagicMock()
    ctx.user_id = user_id
    return ctx


def _req(signal=None, validation_result=None, direction: str = "LONG") -> tuple[ExecutionRequest, MagicMock]:
    sig = signal or _signal(direction=direction)
    account = MagicMock()
    account.balance = Decimal("10000")
    user_ctx = _user_ctx()

    req = ExecutionRequest(
        signal=sig,
        user_ctx=user_ctx,
        account=account,
        daily_loss_usdt=Decimal("50"),
        weekly_loss_usdt=Decimal("100"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions_count=0,
        same_coin_position=None,
    )
    val = validation_result or _validation()
    return req, val


def _make_engine(validation: MagicMock) -> tuple[ShadowExecutionEngine, AsyncMock, AsyncMock]:
    risk = AsyncMock()
    risk.validate = AsyncMock(return_value=validation)
    store = AsyncMock()
    store.save = AsyncMock()
    engine = ShadowExecutionEngine(risk_validator=risk, store=store)
    return engine, risk, store


# ── Group 1: Risk 검증 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_rejected_returns_not_approved():
    req, val = _req(validation_result=_validation(approved=False))
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert not result.approved
    assert not result.executed
    assert result.rejection_code == "RISK_FAIL"


@pytest.mark.asyncio
async def test_risk_rejected_does_not_call_store():
    req, val = _req(validation_result=_validation(approved=False))
    engine, _, store = _make_engine(val)
    await engine.execute(req)
    store.save.assert_not_awaited()


# ── Group 2: 정상 실행 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_execution_calls_store_once():
    req, val = _req()
    engine, _, store = _make_engine(val)
    await engine.execute(req)
    store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_execution_persists_trade_fields():
    sig = _signal(
        direction="LONG",
        entry_price="50000",
        tp_price="55000",
        sl_price="48000",
    )
    req, val = _req(signal=sig, validation_result=_validation(qty="0.0123", leverage=7))
    engine, _, store = _make_engine(val)

    await engine.execute(req)

    record = store.save.await_args.args[0]
    assert record.entry_price == Decimal("50000")
    assert record.tp_price == Decimal("55000")
    assert record.sl_price == Decimal("48000")
    assert record.quantity == Decimal("0.0123")
    assert record.leverage == 7
    assert record.status == "OPEN"


@pytest.mark.asyncio
async def test_successful_execution_returns_paper_mode():
    req, val = _req()
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.approved
    assert result.executed
    assert result.mode == "paper"


@pytest.mark.asyncio
async def test_virtual_orders_use_signal_prices():
    sig = _signal(entry_price="50000", tp_price="55000", sl_price="48000")
    req, val = _req(signal=sig)
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.avg_fill_price == Decimal("50000")
    assert result.tp_order.avg_fill_price == Decimal("55000")
    assert result.sl_order.avg_fill_price == Decimal("48000")


@pytest.mark.asyncio
async def test_virtual_order_ids_contain_shadow_prefix():
    req, val = _req()
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.exchange_order_id.startswith("shadow-entry-")
    assert result.tp_order.exchange_order_id.startswith("shadow-take_profit-")
    assert result.sl_order.exchange_order_id.startswith("shadow-stop_loss-")


@pytest.mark.asyncio
async def test_long_entry_side_is_buy():
    req, val = _req(direction="LONG")
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.side == "BUY"
    assert result.tp_order.side == "SELL"
    assert result.sl_order.side == "SELL"


@pytest.mark.asyncio
async def test_short_entry_side_is_sell():
    req, val = _req(direction="SHORT", signal=_signal(direction="SHORT"))
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.side == "SELL"
    assert result.tp_order.side == "BUY"
    assert result.sl_order.side == "BUY"


# ── Group 3: store 예외 격리 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_exception_returns_system_error():
    req, val = _req()
    engine, _, store = _make_engine(val)
    store.save = AsyncMock(side_effect=RuntimeError("DB down"))
    result = await engine.execute(req)
    assert not result.approved
    assert result.rejection_code == "SYSTEM_ERROR"


@pytest.mark.asyncio
async def test_store_exception_does_not_propagate():
    req, val = _req()
    engine, _, store = _make_engine(val)
    store.save = AsyncMock(side_effect=OSError("disk full"))
    result = await engine.execute(req)  # should not raise
    assert result is not None


# ── Group 4: ShadowTradeRecord 도메인 로직 ────────────────────────────────────

def test_open_classmethod_sets_status_open():
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    assert record.status == "OPEN"
    assert record.exit_price is None
    assert record.pnl_usdt is None


def test_long_tp_hit_pnl():
    """LONG TP_HIT: exit=55000, entry=50000, qty=0.01 → PnL = 50 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("55000"), "TP_HIT")
    assert record.pnl_usdt == pytest.approx(50.0)
    assert record.status == "TP_HIT"
    assert record.exit_price == Decimal("55000")


def test_long_sl_hit_negative_pnl():
    """LONG SL_HIT: exit=48000, entry=50000, qty=0.01 → PnL = -20 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("48000"), "SL_HIT")
    assert record.pnl_usdt == pytest.approx(-20.0)
    assert record.status == "SL_HIT"


def test_short_tp_hit_pnl():
    """SHORT TP_HIT: entry=50000, exit=45000, qty=0.01 → PnL = 50 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="SHORT",
        entry_price=Decimal("50000"),
        tp_price=Decimal("45000"),
        sl_price=Decimal("52000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("45000"), "TP_HIT")
    assert record.pnl_usdt == pytest.approx(50.0)


def test_short_sl_hit_negative_pnl():
    """SHORT SL_HIT: entry=50000, exit=52000, qty=0.01 → PnL = -20 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="SHORT",
        entry_price=Decimal("50000"),
        tp_price=Decimal("45000"),
        sl_price=Decimal("52000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("52000"), "SL_HIT")
    assert record.pnl_usdt == pytest.approx(-20.0)


def test_duration_seconds():
    opened = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    closed = datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc)  # +1h
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
        opened_at=opened,
    )
    record.close(Decimal("55000"), "TP_HIT", closed_at=closed)
    assert record.duration_seconds == pytest.approx(3600.0)
    assert record.closed_at == closed


# ── Group 5: Monitor 로직 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monitor_closes_long_tp_hit():
    """LONG trade: current_price >= tp_price → TP_HIT."""
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades

    trade = MagicMock()
    trade.id = uuid.uuid4()
    trade.symbol = "BTCUSDT"
    trade.direction = "LONG"
    trade.entry_price = Decimal("50000")
    trade.tp_price = Decimal("55000")
    trade.sl_price = Decimal("48000")
    trade.quantity = Decimal("0.01")
    trade.opened_at = datetime.now(timezone.utc) - timedelta(hours=2)

    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])
    repo_mock.close_trade = AsyncMock()

    session_mock = AsyncMock()

    from unittest.mock import patch
    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {"BTCUSDT": Decimal("55500")},
            session_mock,
        )

    assert closed == 1
    call_kwargs = repo_mock.close_trade.call_args
    assert call_kwargs.kwargs["status"] == "TP_HIT"
    assert call_kwargs.kwargs["exit_price"] == Decimal("55000")


@pytest.mark.asyncio
async def test_monitor_closes_short_sl_hit():
    """SHORT trade: current_price >= sl_price → SL_HIT."""
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades
    from unittest.mock import patch

    trade = MagicMock()
    trade.id = uuid.uuid4()
    trade.symbol = "ETHUSDT"
    trade.direction = "SHORT"
    trade.entry_price = Decimal("3000")
    trade.tp_price = Decimal("2700")
    trade.sl_price = Decimal("3200")
    trade.quantity = Decimal("0.1")
    trade.opened_at = datetime.now(timezone.utc) - timedelta(hours=1)

    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])
    repo_mock.close_trade = AsyncMock()

    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {"ETHUSDT": Decimal("3250")},
            AsyncMock(),
        )

    assert closed == 1
    assert repo_mock.close_trade.call_args.kwargs["status"] == "SL_HIT"


@pytest.mark.asyncio
async def test_monitor_skips_trade_price_not_reached():
    """TP/SL 미도달 시 청산하지 않는다."""
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades
    from unittest.mock import patch

    trade = MagicMock()
    trade.id = uuid.uuid4()
    trade.symbol = "BTCUSDT"
    trade.direction = "LONG"
    trade.entry_price = Decimal("50000")
    trade.tp_price = Decimal("55000")
    trade.sl_price = Decimal("48000")
    trade.quantity = Decimal("0.01")
    trade.opened_at = datetime.now(timezone.utc)

    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])
    repo_mock.close_trade = AsyncMock()

    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {"BTCUSDT": Decimal("52000")},  # 중간 가격 — TP/SL 미도달
            AsyncMock(),
        )

    assert closed == 0
    repo_mock.close_trade.assert_not_awaited()
