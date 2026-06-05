"""
MarketDataNormalizer 단위 테스트.

Binance WebSocket 원시 JSON → 내부 모델 변환 검증.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.market_data.normalizer import MarketDataNormalizer
from agents.market_data.models import (
    AggregateTrade,
    CandleCloseEvent,
    KlineData,
    OrderBookData,
    PriceData,
)


# ── Kline 이벤트 ──────────────────────────────────────────────────────────────

_KLINE_CLOSED_EVENT = {
    "e": "kline",
    "E": 1717459800000,
    "s": "BTCUSDT",
    "k": {
        "t": 1717459800000,
        "T": 1717460099999,
        "s": "BTCUSDT",
        "i": "5m",
        "o": "67450.00",
        "c": "67520.00",
        "h": "67580.00",
        "l": "67400.00",
        "v": "123.456",
        "n": 1234,
        "x": True,
    },
}

_KLINE_OPEN_EVENT = {
    **_KLINE_CLOSED_EVENT,
    "k": {**_KLINE_CLOSED_EVENT["k"], "x": False},
}

_ETH_KLINE_EVENT = {
    "e": "kline",
    "E": 1717459800000,
    "s": "ETHUSDT",
    "k": {
        "t": 1717459800000,
        "T": 1717459860000,
        "i": "1m",
        "o": "3500.00",
        "c": "3520.00",
        "h": "3530.00",
        "l": "3490.00",
        "v": "456.789",
        "n": 567,
        "x": True,
    },
}


class TestParseKline:
    def test_symbol_and_coin(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        assert k.symbol == "BTCUSDT"
        assert k.coin == "BTC"

    def test_interval(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        assert k.interval == "5m"

    def test_ohlcv_values(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        assert k.open == Decimal("67450.00")
        assert k.close == Decimal("67520.00")
        assert k.high == Decimal("67580.00")
        assert k.low == Decimal("67400.00")
        assert k.volume == Decimal("123.456")

    def test_num_trades(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        assert k.num_trades == 1234

    def test_is_closed_true(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        assert k.is_closed is True

    def test_is_closed_false(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_OPEN_EVENT)
        assert k.is_closed is False

    def test_open_time_is_utc(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        assert k.open_time.tzinfo is not None
        assert k.open_time == datetime.fromtimestamp(1717459800.0, tz=timezone.utc)

    def test_eth_symbol(self):
        k = MarketDataNormalizer.parse_kline(_ETH_KLINE_EVENT)
        assert k.symbol == "ETHUSDT"
        assert k.coin == "ETH"

    def test_kline_to_price(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        price = MarketDataNormalizer.kline_to_price(k)
        assert isinstance(price, PriceData)
        assert price.price == Decimal("67520.00")
        assert price.coin == "BTC"

    def test_kline_to_candle_event(self):
        k = MarketDataNormalizer.parse_kline(_KLINE_CLOSED_EVENT)
        event = MarketDataNormalizer.kline_to_candle_event(k)
        assert isinstance(event, CandleCloseEvent)
        assert event.event == "candle_closed"
        assert event.coin == "BTC"
        assert event.interval == "5m"
        assert event.close_price == Decimal("67520.00")


# ── AggTrade 이벤트 ───────────────────────────────────────────────────────────

_AGG_TRADE_EVENT = {
    "e": "aggTrade",
    "E": 1717459800000,
    "s": "BTCUSDT",
    "p": "67520.00",
    "q": "0.001",
    "m": False,
    "T": 1717459800100,
}

_AGG_TRADE_SELL_EVENT = {
    **_AGG_TRADE_EVENT,
    "m": True,  # buyer is maker = sell pressure
}


class TestParseAggTrade:
    def test_basic_fields(self):
        t = MarketDataNormalizer.parse_agg_trade(_AGG_TRADE_EVENT)
        assert t.symbol == "BTCUSDT"
        assert t.coin == "BTC"
        assert t.price == Decimal("67520.00")
        assert t.quantity == Decimal("0.001")

    def test_value_calculation(self):
        t = MarketDataNormalizer.parse_agg_trade(_AGG_TRADE_EVENT)
        expected = (Decimal("67520.00") * Decimal("0.001")).quantize(Decimal("0.01"))
        assert t.value == expected

    def test_buyer_maker_false(self):
        t = MarketDataNormalizer.parse_agg_trade(_AGG_TRADE_EVENT)
        assert t.is_buyer_maker is False

    def test_buyer_maker_true(self):
        t = MarketDataNormalizer.parse_agg_trade(_AGG_TRADE_SELL_EVENT)
        assert t.is_buyer_maker is True

    def test_trade_time_is_utc(self):
        t = MarketDataNormalizer.parse_agg_trade(_AGG_TRADE_EVENT)
        assert t.trade_time.tzinfo is not None


# ── Depth 이벤트 ──────────────────────────────────────────────────────────────

_DEPTH_EVENT = {
    "e": "depthUpdate",
    "E": 1717459800000,
    "s": "BTCUSDT",
    "b": [
        ["67450.00", "1.500"],
        ["67440.00", "2.000"],
        ["67430.00", "0.500"],
    ],
    "a": [
        ["67460.00", "0.800"],
        ["67470.00", "1.200"],
    ],
}

_DEPTH_WITH_ZERO_QTY = {
    **_DEPTH_EVENT,
    "b": [["67450.00", "1.5"], ["67440.00", "0"]],  # qty=0은 제거됨
}


class TestParseDepth:
    def test_symbol_and_coin(self):
        book = MarketDataNormalizer.parse_depth(_DEPTH_EVENT)
        assert book.symbol == "BTCUSDT"
        assert book.coin == "BTC"

    def test_bids_count(self):
        book = MarketDataNormalizer.parse_depth(_DEPTH_EVENT)
        assert len(book.bids) == 3

    def test_asks_count(self):
        book = MarketDataNormalizer.parse_depth(_DEPTH_EVENT)
        assert len(book.asks) == 2

    def test_bid_values(self):
        book = MarketDataNormalizer.parse_depth(_DEPTH_EVENT)
        assert book.bids[0].price == Decimal("67450.00")
        assert book.bids[0].quantity == Decimal("1.500")

    def test_ask_values(self):
        book = MarketDataNormalizer.parse_depth(_DEPTH_EVENT)
        assert book.asks[0].price == Decimal("67460.00")

    def test_zero_qty_filtered(self):
        book = MarketDataNormalizer.parse_depth(_DEPTH_WITH_ZERO_QTY)
        # qty=0 인 항목은 제거됨
        for entry in book.bids:
            assert entry.quantity > 0


# ── REST kline 파싱 ───────────────────────────────────────────────────────────

_REST_KLINE_ROW = [
    1717459800000,    # open time
    "67450.00",       # open
    "67580.00",       # high
    "67400.00",       # low
    "67520.00",       # close
    "123.456",        # volume
    1717460099999,    # close time
    "8312345.67",     # quote asset volume
    1234,             # num trades
    "61.728",         # taker buy base volume
    "4156000.00",     # taker buy quote volume
    "0",              # ignore
]


class TestParseKlineRest:
    def test_basic_parse(self):
        k = MarketDataNormalizer.parse_kline_rest(_REST_KLINE_ROW, "BTCUSDT", "5m")
        assert k.symbol == "BTCUSDT"
        assert k.coin == "BTC"
        assert k.interval == "5m"

    def test_ohlcv(self):
        k = MarketDataNormalizer.parse_kline_rest(_REST_KLINE_ROW, "BTCUSDT", "5m")
        assert k.open == Decimal("67450.00")
        assert k.close == Decimal("67520.00")
        assert k.high == Decimal("67580.00")
        assert k.volume == Decimal("123.456")

    def test_num_trades(self):
        k = MarketDataNormalizer.parse_kline_rest(_REST_KLINE_ROW, "BTCUSDT", "5m")
        assert k.num_trades == 1234

    def test_is_always_closed(self):
        k = MarketDataNormalizer.parse_kline_rest(_REST_KLINE_ROW, "BTCUSDT", "5m")
        assert k.is_closed is True  # REST로 가져온 캔들은 항상 완성

    def test_timestamps_are_utc(self):
        k = MarketDataNormalizer.parse_kline_rest(_REST_KLINE_ROW, "BTCUSDT", "5m")
        assert k.open_time.tzinfo is not None
        assert k.close_time.tzinfo is not None
