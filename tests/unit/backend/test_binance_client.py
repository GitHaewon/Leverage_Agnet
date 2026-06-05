"""
Binance 클라이언트 단위 테스트.
Mock 클라이언트는 실제 API 호출 없음.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.clients.binance_mock import BinanceMockClient
from app.clients.binance_base import BinanceAPIError


@pytest.fixture
def mock_client() -> BinanceMockClient:
    return BinanceMockClient()


class TestBinanceMockClientAccountInfo:
    async def test_get_account_info_returns_usdt_balance(
        self, mock_client: BinanceMockClient
    ) -> None:
        info = await mock_client.get_account_info()
        assert info.total_wallet_balance == Decimal("10000.00")
        assert info.can_withdraw is False      # 출금 권한 없음이 정상

    async def test_validate_api_key_no_withdraw(
        self, mock_client: BinanceMockClient
    ) -> None:
        result = await mock_client.validate_api_key()
        assert result.can_trade is True
        assert result.can_futures_trade is True
        assert result.has_withdraw is False    # 반드시 False
        assert result.balance_usdt > 0

    async def test_get_balance_returns_usdt_asset(
        self, mock_client: BinanceMockClient
    ) -> None:
        assets = await mock_client.get_balance()
        usdt = next((a for a in assets if a.asset == "USDT"), None)
        assert usdt is not None
        assert usdt.wallet_balance > 0


class TestBinanceMockClientPositions:
    async def test_no_positions_initially(
        self, mock_client: BinanceMockClient
    ) -> None:
        positions = await mock_client.get_positions()
        assert positions == []

    async def test_position_created_after_market_buy(
        self, mock_client: BinanceMockClient
    ) -> None:
        await mock_client.set_leverage("BTCUSDT", 5)
        await mock_client.create_order(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("0.01"),
        )
        positions = await mock_client.get_positions("BTCUSDT")
        assert len(positions) == 1
        assert positions[0].position_amt > 0   # LONG 포지션

    async def test_invalid_symbol_raises(
        self, mock_client: BinanceMockClient
    ) -> None:
        with pytest.raises(BinanceAPIError) as exc:
            await mock_client.create_order(
                symbol="XYZUSDT",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("1.0"),
            )
        assert exc.value.code == -1121


class TestBinanceMockClientOrders:
    async def test_market_order_filled_immediately(
        self, mock_client: BinanceMockClient
    ) -> None:
        resp = await mock_client.create_order(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("0.01"),
        )
        assert resp.status == "FILLED"
        assert resp.executed_qty == Decimal("0.01")
        assert resp.avg_price is not None
        assert resp.avg_price > 0

    async def test_tpsl_order_new_status(
        self, mock_client: BinanceMockClient
    ) -> None:
        tp_resp = await mock_client.create_order(
            symbol="BTCUSDT",
            side="SELL",
            order_type="TAKE_PROFIT_MARKET",
            quantity=Decimal("0.01"),
            stop_price=Decimal("70000"),
            reduce_only=True,
        )
        assert tp_resp.status == "NEW"

        sl_resp = await mock_client.create_order(
            symbol="BTCUSDT",
            side="SELL",
            order_type="STOP_MARKET",
            quantity=Decimal("0.01"),
            stop_price=Decimal("65000"),
            reduce_only=True,
        )
        assert sl_resp.status == "NEW"

    async def test_cancel_order_success(
        self, mock_client: BinanceMockClient
    ) -> None:
        order = await mock_client.create_order(
            symbol="BTCUSDT",
            side="SELL",
            order_type="TAKE_PROFIT_MARKET",
            quantity=Decimal("0.01"),
            stop_price=Decimal("70000"),
            reduce_only=True,
        )
        cancelled = await mock_client.cancel_order("BTCUSDT", order.order_id)
        assert cancelled.status == "CANCELED"

    async def test_cancel_nonexistent_order_raises(
        self, mock_client: BinanceMockClient
    ) -> None:
        with pytest.raises(BinanceAPIError) as exc:
            await mock_client.cancel_order("BTCUSDT", "nonexistent_id")
        assert exc.value.code == -2013


class TestBinanceMockClientLeverage:
    async def test_set_valid_leverage(self, mock_client: BinanceMockClient) -> None:
        result = await mock_client.set_leverage("BTCUSDT", 10)
        assert result == 10

    async def test_set_invalid_leverage_raises(
        self, mock_client: BinanceMockClient
    ) -> None:
        with pytest.raises(BinanceAPIError) as exc:
            await mock_client.set_leverage("BTCUSDT", 25)   # > 20 한도
        assert exc.value.code == -4003

    async def test_set_leverage_one(self, mock_client: BinanceMockClient) -> None:
        result = await mock_client.set_leverage("BTCUSDT", 1)
        assert result == 1


class TestBinanceMockClientPrice:
    async def test_get_btc_price(self, mock_client: BinanceMockClient) -> None:
        price = await mock_client.get_current_price("BTCUSDT")
        assert price > 0

    async def test_get_eth_price(self, mock_client: BinanceMockClient) -> None:
        price = await mock_client.get_current_price("ETHUSDT")
        assert price > 0

    async def test_invalid_symbol_price_raises(
        self, mock_client: BinanceMockClient
    ) -> None:
        with pytest.raises(BinanceAPIError):
            await mock_client.get_current_price("XYZUSDT")
