"""
MarketDataNormalizer — Binance WebSocket 원시 이벤트 → 내부 모델 변환.

Binance Combined Stream 포맷:
  { "stream": "<symbol>@<type>", "data": { ... } }

각 이벤트 타입:
  "kline"       → KlineData
  "aggTrade"    → AggregateTrade
  "depthUpdate" → OrderBookData

순수 함수 집합 — 외부 의존성 없음, 테스트 가능.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agents.market_data.models import (
    AggregateTrade,
    CandleCloseEvent,
    KlineData,
    OrderBookData,
    OrderBookEntry,
    PriceData,
)


class MarketDataNormalizer:
    """Binance WebSocket 이벤트 파서."""

    # ── Kline (OHLCV) ──────────────────────────────────────────────────────────

    @staticmethod
    def parse_kline(raw: dict[str, Any]) -> KlineData:
        """
        Binance kline 이벤트 파싱.

        raw = {
            "e": "kline", "s": "BTCUSDT",
            "k": {"t": ms, "T": ms, "i": "5m", "o": "...", "c": "...",
                  "h": "...", "l": "...", "v": "...", "n": 1234, "x": true}
        }
        """
        k = raw["k"]
        symbol: str = raw["s"]
        return KlineData(
            symbol=symbol,
            coin=symbol.replace("USDT", ""),
            interval=k["i"],
            open_time=datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc),
            close_time=datetime.fromtimestamp(k["T"] / 1000, tz=timezone.utc),
            open=Decimal(k["o"]),
            high=Decimal(k["h"]),
            low=Decimal(k["l"]),
            close=Decimal(k["c"]),
            volume=Decimal(k["v"]),
            num_trades=int(k.get("n", 0)),
            is_closed=bool(k["x"]),
        )

    @staticmethod
    def kline_to_candle_event(kline: KlineData) -> CandleCloseEvent:
        return CandleCloseEvent(
            event="candle_closed",
            coin=kline.coin,
            symbol=kline.symbol,
            interval=kline.interval,
            close_price=kline.close,
            close_time=kline.close_time,
        )

    @staticmethod
    def kline_to_price(kline: KlineData) -> PriceData:
        return PriceData(
            symbol=kline.symbol,
            coin=kline.coin,
            price=kline.close,
        )

    # ── Aggregate Trade ────────────────────────────────────────────────────────

    @staticmethod
    def parse_agg_trade(raw: dict[str, Any]) -> AggregateTrade:
        """
        raw = {
            "e": "aggTrade", "s": "BTCUSDT",
            "p": "67520.00", "q": "0.001",
            "m": false, "T": ms
        }
        """
        symbol: str = raw["s"]
        price = Decimal(raw["p"])
        quantity = Decimal(raw["q"])
        return AggregateTrade(
            symbol=symbol,
            coin=symbol.replace("USDT", ""),
            price=price,
            quantity=quantity,
            value=(price * quantity).quantize(Decimal("0.01")),
            is_buyer_maker=bool(raw["m"]),
            trade_time=datetime.fromtimestamp(raw["T"] / 1000, tz=timezone.utc),
        )

    # ── Order Book (Depth) ─────────────────────────────────────────────────────

    @staticmethod
    def parse_depth(raw: dict[str, Any]) -> OrderBookData:
        """
        Binance @depth5 이벤트 파싱.

        raw = {
            "e": "depthUpdate", "s": "BTCUSDT",
            "b": [["price", "qty"], ...],
            "a": [["price", "qty"], ...]
        }
        """
        symbol: str = raw["s"]
        return OrderBookData(
            symbol=symbol,
            coin=symbol.replace("USDT", ""),
            bids=[
                OrderBookEntry(Decimal(b[0]), Decimal(b[1]))
                for b in raw.get("b", [])
                if Decimal(b[1]) > 0
            ],
            asks=[
                OrderBookEntry(Decimal(a[0]), Decimal(a[1]))
                for a in raw.get("a", [])
                if Decimal(a[1]) > 0
            ],
        )

    # ── REST 응답 파싱 ─────────────────────────────────────────────────────────

    @staticmethod
    def parse_kline_rest(raw: list[Any], symbol: str, interval: str) -> KlineData:
        """
        Binance REST /fapi/v1/klines 응답 한 행 파싱.

        raw[i] = [open_time_ms, open, high, low, close, volume, ...]
        """
        coin = symbol.replace("USDT", "")
        return KlineData(
            symbol=symbol,
            coin=coin,
            interval=interval,
            open_time=datetime.fromtimestamp(raw[0] / 1000, tz=timezone.utc),
            close_time=datetime.fromtimestamp(raw[6] / 1000, tz=timezone.utc),
            open=Decimal(str(raw[1])),
            high=Decimal(str(raw[2])),
            low=Decimal(str(raw[3])),
            close=Decimal(str(raw[4])),
            volume=Decimal(str(raw[5])),
            num_trades=int(raw[8]) if len(raw) > 8 else 0,
            is_closed=True,  # REST로 가져온 캔들은 이미 완성
        )
