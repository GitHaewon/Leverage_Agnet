"""
MarketDataAgent — pipeline snapshot adapter.

Reads price / kline / funding / OI from Redis and returns a unified
snapshot dict satisfying OrchestratorPipeline.MarketDataProvider.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_SYMBOL_MAP: dict[str, str] = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
_OHLCV_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")


class MarketDataAgent:
    """OrchestratorPipeline.MarketDataProvider protocol implementation."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def get_snapshot(self, coin: str) -> dict[str, Any]:
        symbol = _SYMBOL_MAP.get(coin, f"{coin}USDT")

        price_raw: str | None = await self._redis.get(f"price:{coin}")

        ohlcv: dict[str, Any] = {}
        for interval in _OHLCV_INTERVALS:
            raw = await self._redis.get(f"kline:{symbol}:{interval}:latest")
            if raw:
                try:
                    ohlcv[interval] = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("bad kline JSON: symbol=%s interval=%s", symbol, interval)

        funding_raw: str | None = await self._redis.get(f"funding:{symbol}")
        funding = json.loads(funding_raw) if funding_raw else None

        oi_raw: str | None = await self._redis.get(f"oi:{symbol}")
        oi = json.loads(oi_raw) if oi_raw else None

        return {
            "coin": coin,
            "symbol": symbol,
            "price": price_raw,
            "ohlcv": ohlcv,
            "funding": funding,
            "open_interest": oi,
        }
