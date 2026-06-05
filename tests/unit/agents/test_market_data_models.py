"""
Market Data 모델 단위 테스트.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.market_data.models import (
    AggregateTrade,
    CandleCloseEvent,
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
    STREAM_ANALYSIS_TRIGGER,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _kline(coin="BTC", interval="5m", is_closed=True, close=Decimal("67520")) -> KlineData:
    now = _now()
    return KlineData(
        symbol=f"{coin}USDT",
        coin=coin,
        interval=interval,
        open_time=now,
        close_time=now,
        open=Decimal("67450"),
        high=Decimal("67580"),
        low=Decimal("67400"),
        close=close,
        volume=Decimal("123.456"),
        num_trades=1234,
        is_closed=is_closed,
    )


# ── KlineData ─────────────────────────────────────────────────────────────────

class TestKlineData:
    def test_creation(self):
        k = _kline()
        assert k.symbol == "BTCUSDT"
        assert k.coin == "BTC"
        assert k.interval == "5m"
        assert k.is_closed is True

    def test_as_price_data(self):
        k = _kline(close=Decimal("67520"))
        price = k.as_price_data
        assert isinstance(price, PriceData)
        assert price.coin == "BTC"
        assert price.price == Decimal("67520")

    def test_not_closed(self):
        k = _kline(is_closed=False)
        assert k.is_closed is False

    def test_eth_symbol(self):
        k = _kline(coin="ETH", interval="1h")
        assert k.symbol == "ETHUSDT"
        assert k.coin == "ETH"


# ── OrderBookData ─────────────────────────────────────────────────────────────

class TestOrderBookData:
    def _book(self) -> OrderBookData:
        return OrderBookData(
            symbol="BTCUSDT",
            coin="BTC",
            bids=[
                OrderBookEntry(Decimal("67450"), Decimal("1.5")),
                OrderBookEntry(Decimal("67440"), Decimal("2.0")),
            ],
            asks=[
                OrderBookEntry(Decimal("67460"), Decimal("0.8")),
                OrderBookEntry(Decimal("67470"), Decimal("1.2")),
            ],
        )

    def test_best_bid(self):
        book = self._book()
        assert book.best_bid == Decimal("67450")

    def test_best_ask(self):
        book = self._book()
        assert book.best_ask == Decimal("67460")

    def test_mid_price(self):
        book = self._book()
        expected = (Decimal("67450") + Decimal("67460")) / 2
        assert book.mid_price == expected

    def test_spread(self):
        book = self._book()
        assert book.spread == Decimal("10")

    def test_empty_bids(self):
        book = OrderBookData(symbol="X", coin="X", bids=[], asks=[])
        assert book.best_bid == Decimal("0")
        assert book.mid_price == Decimal("0")


# ── CandleCloseEvent ──────────────────────────────────────────────────────────

class TestCandleCloseEvent:
    def test_to_stream_dict(self):
        event = CandleCloseEvent(
            event="candle_closed",
            coin="BTC",
            symbol="BTCUSDT",
            interval="5m",
            close_price=Decimal("67520"),
            close_time=_now(),
        )
        d = event.to_stream_dict()
        assert d["event"] == "candle_closed"
        assert d["coin"] == "BTC"
        assert d["symbol"] == "BTCUSDT"
        assert d["interval"] == "5m"
        assert d["close_price"] == "67520"
        assert "close_time" in d

    def test_all_fields_are_strings(self):
        event = CandleCloseEvent(
            event="candle_closed",
            coin="ETH",
            symbol="ETHUSDT",
            interval="1h",
            close_price=Decimal("3520.50"),
            close_time=_now(),
        )
        d = event.to_stream_dict()
        for key, val in d.items():
            assert isinstance(val, str), f"{key} should be str, got {type(val)}"


# ── Redis 키 패턴 ─────────────────────────────────────────────────────────────

class TestRedisKeys:
    def test_price_key(self):
        key = REDIS_KEY_PRICE.format(coin="BTC")
        assert key == "price:BTC"

    def test_kline_key(self):
        key = REDIS_KEY_KLINE.format(symbol="BTCUSDT", interval="5m")
        assert key == "kline:BTCUSDT:5m:latest"

    def test_funding_key(self):
        assert REDIS_KEY_FUNDING.format(symbol="BTCUSDT") == "funding:BTCUSDT"

    def test_oi_key(self):
        assert REDIS_KEY_OI.format(symbol="ETHUSDT") == "oi:ETHUSDT"

    def test_orderbook_key(self):
        assert REDIS_KEY_ORDERBOOK.format(symbol="BTCUSDT") == "orderbook:BTCUSDT"

    def test_stream_name(self):
        assert STREAM_ANALYSIS_TRIGGER == "stream:analysis_trigger"


# ── FundingRateData ───────────────────────────────────────────────────────────

class TestFundingRateData:
    def test_creation(self):
        fr = FundingRateData(
            symbol="BTCUSDT",
            coin="BTC",
            funding_rate=Decimal("-0.0002"),
            mark_price=Decimal("67450"),
            index_price=Decimal("67430"),
            next_funding_time=_now(),
        )
        assert fr.funding_rate == Decimal("-0.0002")
        assert fr.coin == "BTC"


# ── OpenInterestData ──────────────────────────────────────────────────────────

class TestOpenInterestData:
    def test_creation(self):
        oi = OpenInterestData(
            symbol="BTCUSDT",
            coin="BTC",
            open_interest=Decimal("28451234.567"),
            open_interest_value=Decimal("1916931234567.0"),
        )
        assert oi.open_interest > 0


# ── AggregateTrade ─────────────────────────────────────────────────────────────

class TestAggregateTrade:
    def test_creation(self):
        trade = AggregateTrade(
            symbol="BTCUSDT",
            coin="BTC",
            price=Decimal("67520"),
            quantity=Decimal("0.001"),
            value=Decimal("67.52"),
            is_buyer_maker=False,
            trade_time=_now(),
        )
        assert trade.is_buyer_maker is False
        assert trade.value == Decimal("67.52")
