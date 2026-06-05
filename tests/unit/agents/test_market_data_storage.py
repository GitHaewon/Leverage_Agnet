"""
MarketDataStorage 단위 테스트 — Redis Mock 사용.

DB 저장 테스트는 통합 테스트로 분리.
Redis 캐시 read/write 정확성 + 키 패턴 검증.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agents.market_data.models import (
    FundingRateData,
    KlineData,
    OpenInterestData,
    OrderBookData,
    OrderBookEntry,
    PriceData,
    REDIS_KEY_FUNDING,
    REDIS_KEY_KLINE,
    REDIS_KEY_OI,
    REDIS_KEY_ORDERBOOK,
    REDIS_KEY_PRICE,
    TTL_FUNDING,
    TTL_KLINE,
    TTL_OI,
    TTL_ORDERBOOK,
    TTL_PRICE,
)
from agents.market_data.storage import MarketDataStorage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    return redis


def _make_db_factory():
    """No-op DB factory (DB 테스트는 통합 테스트에서)."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory, mock_session


def _kline(is_closed=True) -> KlineData:
    now = _now()
    return KlineData(
        symbol="BTCUSDT", coin="BTC", interval="5m",
        open_time=now, close_time=now,
        open=Decimal("67450"), high=Decimal("67580"),
        low=Decimal("67400"), close=Decimal("67520"),
        volume=Decimal("123.456"), num_trades=1234,
        is_closed=is_closed,
    )


# ── Redis: 현재가 캐시 ────────────────────────────────────────────────────────

class TestCachePrice:
    @pytest.mark.asyncio
    async def test_set_called_with_correct_key(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        price = PriceData(symbol="BTCUSDT", coin="BTC", price=Decimal("67520"))
        await storage.cache_price(price)

        redis.set.assert_called_once()
        args, kwargs = redis.set.call_args
        assert args[0] == "price:BTC"
        assert kwargs.get("ex") == TTL_PRICE

    @pytest.mark.asyncio
    async def test_price_json_content(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        price = PriceData(symbol="BTCUSDT", coin="BTC", price=Decimal("67520"))
        await storage.cache_price(price)

        args, _ = redis.set.call_args
        payload = json.loads(args[1])
        assert payload["coin"] == "BTC"
        assert payload["price"] == "67520"
        assert "updated_at" in payload

    @pytest.mark.asyncio
    async def test_get_price_returns_none_on_miss(self):
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        result = await storage.get_price("BTC")
        assert result is None
        redis.get.assert_called_with("price:BTC")

    @pytest.mark.asyncio
    async def test_get_price_returns_decimal_on_hit(self):
        redis = _make_redis()
        redis.get = AsyncMock(return_value=json.dumps({
            "coin": "BTC", "symbol": "BTCUSDT",
            "price": "67520.00", "updated_at": _now().isoformat(),
        }))
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        result = await storage.get_price("BTC")
        assert result == Decimal("67520.00")


# ── Redis: 캔들 캐시 ──────────────────────────────────────────────────────────

class TestCacheKline:
    @pytest.mark.asyncio
    async def test_key_pattern(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        await storage.cache_kline(_kline())

        args, kwargs = redis.set.call_args
        assert args[0] == "kline:BTCUSDT:5m:latest"
        assert kwargs.get("ex") == TTL_KLINE

    @pytest.mark.asyncio
    async def test_kline_json_has_ohlcv(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        await storage.cache_kline(_kline())

        args, _ = redis.set.call_args
        payload = json.loads(args[1])
        assert "open" in payload
        assert "close" in payload
        assert "volume" in payload
        assert payload["interval"] == "5m"
        assert payload["is_closed"] is True


# ── Redis: Funding Rate 캐시 ──────────────────────────────────────────────────

class TestCacheFunding:
    @pytest.mark.asyncio
    async def test_key_and_ttl(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        fr = FundingRateData(
            symbol="BTCUSDT", coin="BTC",
            funding_rate=Decimal("-0.0002"),
            mark_price=Decimal("67450"),
            index_price=Decimal("67430"),
            next_funding_time=_now(),
        )
        await storage.cache_funding(fr)

        args, kwargs = redis.set.call_args
        assert args[0] == "funding:BTCUSDT"
        assert kwargs.get("ex") == TTL_FUNDING

    @pytest.mark.asyncio
    async def test_funding_rate_in_payload(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        fr = FundingRateData(
            symbol="BTCUSDT", coin="BTC",
            funding_rate=Decimal("-0.0002"),
            mark_price=Decimal("67450"),
            index_price=Decimal("67430"),
            next_funding_time=_now(),
        )
        await storage.cache_funding(fr)

        args, _ = redis.set.call_args
        payload = json.loads(args[1])
        assert payload["funding_rate"] == "-0.0002"

    @pytest.mark.asyncio
    async def test_get_funding_returns_none_on_miss(self):
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        result = await storage.get_funding("BTCUSDT")
        assert result is None


# ── Redis: Open Interest 캐시 ─────────────────────────────────────────────────

class TestCacheOpenInterest:
    @pytest.mark.asyncio
    async def test_key_and_ttl(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        oi = OpenInterestData(
            symbol="BTCUSDT", coin="BTC",
            open_interest=Decimal("28451234.567"),
            open_interest_value=Decimal("1916931234567.0"),
        )
        await storage.cache_open_interest(oi)

        args, kwargs = redis.set.call_args
        assert args[0] == "oi:BTCUSDT"
        assert kwargs.get("ex") == TTL_OI


# ── Redis: OrderBook 캐시 ────────────────────────────────────────────────────

class TestCacheOrderBook:
    @pytest.mark.asyncio
    async def test_key_and_ttl(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        book = OrderBookData(
            symbol="BTCUSDT", coin="BTC",
            bids=[OrderBookEntry(Decimal("67450"), Decimal("1.5"))],
            asks=[OrderBookEntry(Decimal("67460"), Decimal("0.8"))],
        )
        await storage.cache_orderbook(book)

        args, kwargs = redis.set.call_args
        assert args[0] == "orderbook:BTCUSDT"
        assert kwargs.get("ex") == TTL_ORDERBOOK

    @pytest.mark.asyncio
    async def test_orderbook_payload_has_prices(self):
        redis = _make_redis()
        factory, _ = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        book = OrderBookData(
            symbol="BTCUSDT", coin="BTC",
            bids=[OrderBookEntry(Decimal("67450"), Decimal("1.5"))],
            asks=[OrderBookEntry(Decimal("67460"), Decimal("0.8"))],
        )
        await storage.cache_orderbook(book)

        args, _ = redis.set.call_args
        payload = json.loads(args[1])
        assert payload["best_bid"] == "67450"
        assert payload["best_ask"] == "67460"
        assert len(payload["bids"]) == 1
        assert len(payload["asks"]) == 1


# ── DB: OHLCV 저장 ────────────────────────────────────────────────────────────

class TestPersistKline:
    @pytest.mark.asyncio
    async def test_persist_calls_execute(self):
        redis = _make_redis()
        factory, mock_session = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        await storage.persist_kline(_kline(is_closed=True))

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_persist_empty_list(self):
        redis = _make_redis()
        factory, mock_session = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        count = await storage.bulk_persist_klines([])
        assert count == 0
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_persist_multiple(self):
        redis = _make_redis()
        factory, mock_session = _make_db_factory()
        storage = MarketDataStorage(redis, factory)

        klines = [_kline() for _ in range(5)]
        count = await storage.bulk_persist_klines(klines)
        assert count == 5
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
