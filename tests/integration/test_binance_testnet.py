"""
Binance Testnet 통합 테스트.

필수 환경변수:
  BINANCE_TESTNET=true
  BINANCE_TESTNET_API_KEY=<testnet key>
  BINANCE_TESTNET_API_SECRET=<testnet secret>

실행: pytest tests/integration/test_binance_testnet.py -v -m integration
Testnet 자격증명 없으면 skip.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration

_TESTNET_KEY = os.getenv("BINANCE_TESTNET_API_KEY", "")
_TESTNET_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET", "")
_HAS_CREDENTIALS = bool(_TESTNET_KEY and _TESTNET_SECRET)

skip_no_creds = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET not set",
)


@skip_no_creds
class TestBinanceTestnetREST:
    """실제 Binance Testnet API 호출 — 자격증명 필요."""

    @pytest.fixture
    def testnet_client(self):
        from app.clients.binance_rest import BinanceRESTClient
        from app.core.config import settings
        return BinanceRESTClient(
            api_key=_TESTNET_KEY,
            api_secret=_TESTNET_SECRET,
            base_url=settings.BINANCE_TESTNET_BASE_URL,
        )

    async def test_validate_api_key_real(self, testnet_client) -> None:
        try:
            result = await testnet_client.validate_api_key()
            assert result.can_trade is True
            assert result.has_withdraw is False, (
                "출금 권한이 있는 Testnet 키 — 실제 사용 금지"
            )
        finally:
            await testnet_client.aclose()

    async def test_get_balance_real(self, testnet_client) -> None:
        try:
            assets = await testnet_client.get_balance()
            assert len(assets) > 0
            usdt = next((a for a in assets if a.asset == "USDT"), None)
            assert usdt is not None
        finally:
            await testnet_client.aclose()

    async def test_get_positions_real(self, testnet_client) -> None:
        try:
            positions = await testnet_client.get_positions()
            # Testnet에 포지션이 없을 수 있으므로 빈 리스트도 OK
            assert isinstance(positions, list)
        finally:
            await testnet_client.aclose()

    async def test_get_current_price_real(self, testnet_client) -> None:
        try:
            price = await testnet_client.get_current_price("BTCUSDT")
            assert price > 0
        finally:
            await testnet_client.aclose()

    async def test_set_leverage_real(self, testnet_client) -> None:
        try:
            result = await testnet_client.set_leverage("BTCUSDT", 5)
            assert 1 <= result <= 20
        finally:
            await testnet_client.aclose()

    async def test_create_small_market_order_real(self, testnet_client) -> None:
        """
        Testnet 소액 시장가 주문 + 즉시 취소.
        최소 수량: BTC 0.001, ETH 0.01
        """
        try:
            # 레버리지 설정
            await testnet_client.set_leverage("BTCUSDT", 1)

            # 소량 매수
            entry = await testnet_client.create_order(
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("0.001"),
            )
            assert entry.status == "FILLED"
            assert entry.executed_qty == Decimal("0.001")
            assert entry.avg_price is not None

            # SL 주문 (필수)
            sl = await testnet_client.create_order(
                symbol="BTCUSDT",
                side="SELL",
                order_type="STOP_MARKET",
                quantity=Decimal("0.001"),
                stop_price=entry.avg_price * Decimal("0.90"),   # 10% SL
                reduce_only=True,
            )
            assert sl.status == "NEW"

            # SL 주문 취소 (테스트 정리)
            cancelled = await testnet_client.cancel_order("BTCUSDT", sl.order_id)
            assert cancelled.status == "CANCELED"

            # 포지션 청산
            close = await testnet_client.create_order(
                symbol="BTCUSDT",
                side="SELL",
                order_type="MARKET",
                quantity=Decimal("0.001"),
                reduce_only=True,
            )
            assert close.status == "FILLED"

        finally:
            await testnet_client.aclose()


class TestBinanceMockIntegration:
    """Mock 클라이언트 통합 플로우 — 자격증명 불필요."""

    async def test_full_trade_cycle_mock(self) -> None:
        """진입 → TP/SL 설정 → 취소 전체 사이클."""
        from app.clients.binance_mock import BinanceMockClient
        client = BinanceMockClient()

        # 레버리지 설정
        lev = await client.set_leverage("BTCUSDT", 5)
        assert lev == 5

        # 시장가 진입
        entry = await client.create_order(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("0.01"),
        )
        assert entry.status == "FILLED"

        # TP 주문
        tp = await client.create_order(
            symbol="BTCUSDT",
            side="SELL",
            order_type="TAKE_PROFIT_MARKET",
            quantity=Decimal("0.01"),
            stop_price=Decimal("70000"),
            reduce_only=True,
        )

        # SL 주문
        sl = await client.create_order(
            symbol="BTCUSDT",
            side="SELL",
            order_type="STOP_MARKET",
            quantity=Decimal("0.01"),
            stop_price=Decimal("65000"),
            reduce_only=True,
        )

        # 오픈 주문 확인
        open_orders = await client.get_open_orders("BTCUSDT")
        assert len(open_orders) == 2

        # TP 취소
        cancelled = await client.cancel_order("BTCUSDT", tp.order_id)
        assert cancelled.status == "CANCELED"

        # 나머지 오픈 주문 1개 (SL만)
        open_orders = await client.get_open_orders("BTCUSDT")
        assert len(open_orders) == 1
        assert open_orders[0].order_id == sl.order_id

    async def test_no_withdraw_permission_in_mock(self) -> None:
        """Mock은 항상 출금 권한 없음으로 응답."""
        from app.clients.binance_mock import BinanceMockClient
        client = BinanceMockClient()
        result = await client.validate_api_key()
        assert result.has_withdraw is False

    async def test_leverage_capped_at_20(self) -> None:
        """레버리지 20 초과 설정 시 에러."""
        from app.clients.binance_mock import BinanceMockClient
        from app.clients.binance_base import BinanceAPIError
        client = BinanceMockClient()
        with pytest.raises(BinanceAPIError):
            await client.set_leverage("BTCUSDT", 21)
