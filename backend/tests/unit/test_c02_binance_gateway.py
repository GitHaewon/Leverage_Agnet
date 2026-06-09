"""
C-02 단위 테스트 — BinanceGateway (ExecutionEngine ↔ BinanceService 브릿지).

외부 의존성(Binance API, DB, crypto)은 모두 Mock. 실제 Binance API 호출 없음.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.execution.models import FilledOrder, OrderTicket


# ── 픽스처 ──────────────────────────────────────────────────────────────────────


def _make_ticket(
    purpose: str = "entry",
    order_type: str = "MARKET",
    price: Decimal = Decimal("50000"),
    reduce_only: bool = False,
) -> OrderTicket:
    return OrderTicket(
        symbol="BTCUSDT",
        side="BUY",
        order_type=order_type,
        quantity=Decimal("0.001"),
        price=price,
        reduce_only=reduce_only,
        purpose=purpose,
    )


def _make_order_response(
    order_id: str = "12345",
    avg_price: Decimal | None = Decimal("50010"),
    executed_qty: Decimal = Decimal("0.001"),
    order_type: str = "MARKET",
    side: str = "BUY",
):
    resp = MagicMock()
    resp.order_id = order_id
    resp.symbol = "BTCUSDT"
    resp.avg_price = avg_price
    resp.executed_qty = executed_qty
    resp.order_type = order_type
    resp.side = side
    resp.status = "FILLED"
    return resp


def _make_mock_account(is_testnet: bool = True):
    account = MagicMock()
    account.encrypted_api_key = "encrypted_key"
    account.encrypted_api_secret = "encrypted_secret"
    account.is_testnet = is_testnet
    return account


# ── _ticket_to_kwargs ────────────────────────────────────────────────────────────


def test_ticket_to_kwargs_market_entry():
    from app.gateways.binance_gateway import _ticket_to_kwargs
    ticket = _make_ticket(order_type="MARKET", reduce_only=False)
    kwargs = _ticket_to_kwargs(ticket)
    assert kwargs["order_type"] == "MARKET"
    assert "stop_price" not in kwargs
    assert "reduce_only" not in kwargs


def test_ticket_to_kwargs_take_profit():
    from app.gateways.binance_gateway import _ticket_to_kwargs
    ticket = _make_ticket(
        purpose="take_profit",
        order_type="TAKE_PROFIT_MARKET",
        price=Decimal("55000"),
        reduce_only=True,
    )
    kwargs = _ticket_to_kwargs(ticket)
    assert kwargs["stop_price"] == Decimal("55000")
    assert kwargs["reduce_only"] is True
    assert "price" not in kwargs


def test_ticket_to_kwargs_stop_loss():
    from app.gateways.binance_gateway import _ticket_to_kwargs
    ticket = _make_ticket(
        purpose="stop_loss",
        order_type="STOP_MARKET",
        price=Decimal("45000"),
        reduce_only=True,
    )
    kwargs = _ticket_to_kwargs(ticket)
    assert kwargs["stop_price"] == Decimal("45000")
    assert kwargs["reduce_only"] is True


# ── _to_filled_order ─────────────────────────────────────────────────────────────


def test_to_filled_order_uses_avg_price():
    from app.gateways.binance_gateway import _to_filled_order
    ticket = _make_ticket()
    resp = _make_order_response(avg_price=Decimal("50100"))
    result = _to_filled_order(ticket, resp)
    assert result.avg_fill_price == Decimal("50100.00")
    assert result.purpose == "entry"
    assert result.exchange_order_id == "12345"


def test_to_filled_order_falls_back_to_ticket_price_when_avg_zero():
    from app.gateways.binance_gateway import _to_filled_order
    ticket = _make_ticket(price=Decimal("50000"))
    resp = _make_order_response(avg_price=Decimal("0"))
    result = _to_filled_order(ticket, resp)
    assert result.avg_fill_price == Decimal("50000.00")


def test_to_filled_order_falls_back_to_ticket_qty_when_executed_zero():
    from app.gateways.binance_gateway import _to_filled_order
    ticket = _make_ticket()
    resp = _make_order_response(executed_qty=Decimal("0"))
    result = _to_filled_order(ticket, resp)
    assert result.quantity == ticket.quantity


def test_to_filled_order_fee_is_positive():
    from app.gateways.binance_gateway import _to_filled_order
    ticket = _make_ticket()
    resp = _make_order_response()
    result = _to_filled_order(ticket, resp)
    assert result.fee_usdt > Decimal("0")
    assert isinstance(result.filled_at, datetime)


# ── BinanceGateway.place_order ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_place_order_success():
    from app.gateways.binance_gateway import BinanceGateway

    user_id = uuid.uuid4()
    ticket = _make_ticket()
    mock_resp = _make_order_response()
    mock_account = _make_mock_account(is_testnet=True)
    mock_client = AsyncMock()
    mock_client.create_order = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    class _MockSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        execute = AsyncMock()

    mock_repo = AsyncMock()
    mock_repo.get_active_by_user = AsyncMock(return_value=mock_account)

    with (
        patch("app.gateways.binance_gateway.settings") as mock_settings,
        patch("app.core.database.AsyncSessionLocal", _MockSession),
        patch("app.gateways.binance_gateway.ExchangeAccountRepository", return_value=mock_repo),
        patch("app.gateways.binance_gateway.decrypt", return_value="plain"),
        patch("app.gateways.binance_gateway.create_binance_client", return_value=mock_client),
    ):
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.BINANCE_TESTNET = True

        gw = BinanceGateway(user_id=user_id, is_testnet=True)
        result = await gw.place_order(ticket)

    assert isinstance(result, FilledOrder)
    assert result.exchange_order_id == "12345"
    mock_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_place_order_raises_when_no_account():
    from app.gateways.binance_gateway import BinanceGateway

    user_id = uuid.uuid4()
    ticket = _make_ticket()
    mock_repo = AsyncMock()
    mock_repo.get_active_by_user = AsyncMock(return_value=None)

    class _MockSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    with (
        patch("app.core.database.AsyncSessionLocal", _MockSession),
        patch("app.gateways.binance_gateway.ExchangeAccountRepository", return_value=mock_repo),
    ):
        gw = BinanceGateway(user_id=user_id, is_testnet=True)
        with pytest.raises(RuntimeError, match="No active exchange account"):
            await gw.place_order(ticket)


@pytest.mark.asyncio
async def test_place_order_blocks_mainnet_when_live_trading_disabled():
    """LIVE_TRADING_ENABLED=false면 mainnet 계좌 주문을 게이트웨이 레벨에서 차단."""
    from app.gateways.binance_gateway import BinanceGateway

    user_id = uuid.uuid4()
    ticket = _make_ticket()
    mock_account = _make_mock_account(is_testnet=False)  # mainnet 계좌!
    mock_repo = AsyncMock()
    mock_repo.get_active_by_user = AsyncMock(return_value=mock_account)

    class _MockSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    with (
        patch("app.gateways.binance_gateway.settings") as mock_settings,
        patch("app.core.database.AsyncSessionLocal", _MockSession),
        patch("app.gateways.binance_gateway.ExchangeAccountRepository", return_value=mock_repo),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False  # 기본값 유지
        gw = BinanceGateway(user_id=user_id, is_testnet=False)
        with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED=false"):
            await gw.place_order(ticket)


@pytest.mark.asyncio
async def test_cancel_all_orders_returns_count():
    from app.gateways.binance_gateway import BinanceGateway

    user_id = uuid.uuid4()
    mock_account = _make_mock_account(is_testnet=True)
    mock_repo = AsyncMock()
    mock_repo.get_active_by_user = AsyncMock(return_value=mock_account)

    open_order_1 = MagicMock(order_id="111")
    open_order_2 = MagicMock(order_id="222")
    mock_client = AsyncMock()
    mock_client.get_open_orders = AsyncMock(return_value=[open_order_1, open_order_2])
    mock_client.cancel_order = AsyncMock()
    mock_client.aclose = AsyncMock()

    class _MockSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    with (
        patch("app.core.database.AsyncSessionLocal", _MockSession),
        patch("app.gateways.binance_gateway.ExchangeAccountRepository", return_value=mock_repo),
        patch("app.gateways.binance_gateway.decrypt", return_value="plain"),
        patch("app.gateways.binance_gateway.create_binance_client", return_value=mock_client),
    ):
        gw = BinanceGateway(user_id=user_id, is_testnet=True)
        count = await gw.cancel_all_orders("BTCUSDT")

    assert count == 2
    assert mock_client.cancel_order.await_count == 2
    mock_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_all_orders_returns_zero_when_no_account():
    from app.gateways.binance_gateway import BinanceGateway

    mock_repo = AsyncMock()
    mock_repo.get_active_by_user = AsyncMock(return_value=None)

    class _MockSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    with (
        patch("app.core.database.AsyncSessionLocal", _MockSession),
        patch("app.gateways.binance_gateway.ExchangeAccountRepository", return_value=mock_repo),
    ):
        gw = BinanceGateway(user_id=uuid.uuid4(), is_testnet=True)
        count = await gw.cancel_all_orders("BTCUSDT")

    assert count == 0
