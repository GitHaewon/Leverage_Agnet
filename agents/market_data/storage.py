"""
MarketDataStorage — Redis 캐시 + TimescaleDB UPSERT.

잔고 모델:
  Redis Cache:
    price:{coin}              → 현재가 JSON (TTL 1s)
    kline:{sym}:{int}:latest  → 최신 캔들 JSON (TTL 5m)
    funding:{symbol}          → Funding Rate JSON (TTL 1m)
    oi:{symbol}               → Open Interest JSON (TTL 5m)
    orderbook:{symbol}        → 호가창 JSON (TTL 5s)

  TimescaleDB:
    ohlcv 테이블 UPSERT (is_closed=True 캔들만)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncContextManager, Callable

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents.market_data.models import (
    FundingRateData,
    KlineData,
    OpenInterestData,
    OrderBookData,
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

logger = logging.getLogger(__name__)

# DB 세션 팩토리 타입 (async context manager 반환)
DbFactory = Callable[[], AsyncContextManager[AsyncSession]]

# TimescaleDB UPSERT SQL
_OHLCV_UPSERT_SQL = text("""
    INSERT INTO ohlcv (time, coin, interval, open, high, low, close, volume)
    VALUES (:time, :coin, :interval, :open, :high, :low, :close, :volume)
    ON CONFLICT (time, coin, interval)
    DO UPDATE SET
        open   = EXCLUDED.open,
        high   = EXCLUDED.high,
        low    = EXCLUDED.low,
        close  = EXCLUDED.close,
        volume = EXCLUDED.volume
""")

_OHLCV_BULK_UPSERT_SQL = text("""
    INSERT INTO ohlcv (time, coin, interval, open, high, low, close, volume)
    VALUES (:time, :coin, :interval, :open, :high, :low, :close, :volume)
    ON CONFLICT (time, coin, interval)
    DO UPDATE SET
        open   = EXCLUDED.open,
        high   = EXCLUDED.high,
        low    = EXCLUDED.low,
        close  = EXCLUDED.close,
        volume = EXCLUDED.volume
""")


def _decimal_str(v: Decimal | float | str) -> str:
    return str(v) if isinstance(v, str) else f"{v}"


class MarketDataStorage:
    """Redis 캐시 + TimescaleDB 저장소."""

    def __init__(self, redis: aioredis.Redis, db_factory: DbFactory) -> None:
        self._redis = redis
        self._db = db_factory

    # ── Redis: 현재가 ──────────────────────────────────────────────────────────

    async def cache_price(self, data: PriceData) -> None:
        key = REDIS_KEY_PRICE.format(coin=data.coin)
        payload = json.dumps({
            "coin": data.coin,
            "symbol": data.symbol,
            "price": _decimal_str(data.price),
            "updated_at": data.updated_at.isoformat(),
        })
        await self._redis.set(key, payload, ex=TTL_PRICE)

    async def get_price(self, coin: str) -> Decimal | None:
        key = REDIS_KEY_PRICE.format(coin=coin)
        raw = await self._redis.get(key)
        if raw:
            return Decimal(json.loads(raw)["price"])
        return None

    # ── Redis: 캔들 ───────────────────────────────────────────────────────────

    async def cache_kline(self, kline: KlineData) -> None:
        key = REDIS_KEY_KLINE.format(symbol=kline.symbol, interval=kline.interval)
        payload = json.dumps({
            "symbol": kline.symbol,
            "coin": kline.coin,
            "interval": kline.interval,
            "open": _decimal_str(kline.open),
            "high": _decimal_str(kline.high),
            "low": _decimal_str(kline.low),
            "close": _decimal_str(kline.close),
            "volume": _decimal_str(kline.volume),
            "open_time": kline.open_time.isoformat(),
            "close_time": kline.close_time.isoformat(),
            "is_closed": kline.is_closed,
        })
        await self._redis.set(key, payload, ex=TTL_KLINE)

    # ── Redis: Funding Rate ────────────────────────────────────────────────────

    async def cache_funding(self, data: FundingRateData) -> None:
        key = REDIS_KEY_FUNDING.format(symbol=data.symbol)
        payload = json.dumps({
            "symbol": data.symbol,
            "coin": data.coin,
            "funding_rate": _decimal_str(data.funding_rate),
            "mark_price": _decimal_str(data.mark_price),
            "index_price": _decimal_str(data.index_price),
            "next_funding_time": data.next_funding_time.isoformat(),
            "fetched_at": data.fetched_at.isoformat(),
        })
        await self._redis.set(key, payload, ex=TTL_FUNDING)

    async def get_funding(self, symbol: str) -> dict[str, Any] | None:
        key = REDIS_KEY_FUNDING.format(symbol=symbol)
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    # ── Redis: Open Interest ───────────────────────────────────────────────────

    async def cache_open_interest(self, data: OpenInterestData) -> None:
        key = REDIS_KEY_OI.format(symbol=data.symbol)
        payload = json.dumps({
            "symbol": data.symbol,
            "coin": data.coin,
            "open_interest": _decimal_str(data.open_interest),
            "open_interest_value": _decimal_str(data.open_interest_value),
            "fetched_at": data.fetched_at.isoformat(),
        })
        await self._redis.set(key, payload, ex=TTL_OI)

    async def get_open_interest(self, symbol: str) -> dict[str, Any] | None:
        key = REDIS_KEY_OI.format(symbol=symbol)
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    # ── Redis: Order Book ──────────────────────────────────────────────────────

    async def cache_orderbook(self, book: OrderBookData) -> None:
        key = REDIS_KEY_ORDERBOOK.format(symbol=book.symbol)
        payload = json.dumps({
            "symbol": book.symbol,
            "coin": book.coin,
            "best_bid": _decimal_str(book.best_bid),
            "best_ask": _decimal_str(book.best_ask),
            "mid_price": _decimal_str(book.mid_price),
            "spread": _decimal_str(book.spread),
            "bids": [[_decimal_str(b.price), _decimal_str(b.quantity)] for b in book.bids],
            "asks": [[_decimal_str(a.price), _decimal_str(a.quantity)] for a in book.asks],
            "updated_at": book.updated_at.isoformat(),
        })
        await self._redis.set(key, payload, ex=TTL_ORDERBOOK)

    # ── TimescaleDB: OHLCV 단건 저장 ──────────────────────────────────────────

    async def persist_kline(self, kline: KlineData) -> None:
        """완성된 캔들(is_closed=True)을 TimescaleDB에 UPSERT."""
        try:
            async with self._db() as session:
                await session.execute(
                    _OHLCV_UPSERT_SQL,
                    {
                        "time": kline.open_time,
                        "coin": kline.coin,
                        "interval": kline.interval,
                        "open": float(kline.open),
                        "high": float(kline.high),
                        "low": float(kline.low),
                        "close": float(kline.close),
                        "volume": float(kline.volume),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.error(
                "OHLCV persist failed symbol=%s interval=%s time=%s err=%s",
                kline.symbol, kline.interval, kline.open_time, exc,
            )

    # ── TimescaleDB: OHLCV 벌크 저장 (Backfill용) ────────────────────────────

    async def bulk_persist_klines(self, klines: list[KlineData]) -> int:
        """누락 캔들 복구용 벌크 UPSERT. 저장된 건수 반환."""
        if not klines:
            return 0

        rows = [
            {
                "time": k.open_time,
                "coin": k.coin,
                "interval": k.interval,
                "open": float(k.open),
                "high": float(k.high),
                "low": float(k.low),
                "close": float(k.close),
                "volume": float(k.volume),
            }
            for k in klines
        ]

        try:
            async with self._db() as session:
                await session.execute(_OHLCV_BULK_UPSERT_SQL, rows)
                await session.commit()
            logger.info("Bulk persisted %d klines", len(rows))
            return len(rows)
        except Exception as exc:
            logger.error("Bulk OHLCV persist failed: %s", exc)
            return 0

    # ── 헬스 체크용 최신 캔들 시간 조회 ──────────────────────────────────────

    async def get_latest_kline_time(
        self, coin: str, interval: str
    ) -> datetime | None:
        """DB에서 특정 코인/인터벌의 가장 최신 캔들 시간 조회."""
        try:
            async with self._db() as session:
                result = await session.execute(
                    text(
                        "SELECT MAX(time) FROM ohlcv "
                        "WHERE coin = :coin AND interval = :interval"
                    ),
                    {"coin": coin, "interval": interval},
                )
                row = result.scalar_one_or_none()
                return row
        except Exception as exc:
            logger.error("get_latest_kline_time failed: %s", exc)
            return None
