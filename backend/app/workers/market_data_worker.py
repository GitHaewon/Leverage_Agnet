"""
Market Data Worker — Binance Futures REST API에서 시장 데이터를 수집해 Redis에 저장한다.

1분마다 실행:
  - 현재가 (price:BTC, price:BTCUSDT)
  - OHLCV 캔들 200개 (kline:BTCUSDT:{interval}:latest)
  - 펀딩비 (funding:BTCUSDT)
  - 미결제 약정 (oi:BTCUSDT)
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import redis.asyncio as aioredis

from app.core.config import settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# 시장 데이터는 항상 메인넷에서 수집 (퍼블릭 엔드포인트, 인증 불필요)
_BASE_URL = "https://fapi.binance.com"
_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
_KLINE_LIMIT = 200


@celery_app.task(
    name="app.workers.market_data_worker.fetch_market_data",
    acks_late=True,
)
def fetch_market_data() -> None:
    """1분마다 실행 — Binance REST에서 시장 데이터 수집."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_fetch_all())
    finally:
        loop.close()


async def _fetch_all() -> None:
    redis = aioredis.from_url(str(settings.REDIS_URL), decode_responses=True)
    try:
        async with httpx.AsyncClient(base_url=_BASE_URL, timeout=15.0) as client:
            for symbol in _SYMBOLS:
                coin = symbol.replace("USDT", "")
                try:
                    await _fetch_symbol(client, redis, symbol, coin)
                except Exception as exc:
                    logger.error("market_data fetch failed symbol=%s: %s", symbol, exc)
    finally:
        await redis.aclose()


async def _fetch_symbol(
    client: httpx.AsyncClient,
    redis: aioredis.Redis,
    symbol: str,
    coin: str,
) -> None:
    # ── 현재가 ────────────────────────────────────────────────────────────────
    price_resp = await client.get("/fapi/v1/ticker/price", params={"symbol": symbol})
    price_resp.raise_for_status()
    price = price_resp.json()["price"]
    await redis.set(f"price:{coin}", price, ex=120)
    await redis.set(f"price:{symbol}", price, ex=120)

    # ── OHLCV 캔들 (타임프레임별 200개) ──────────────────────────────────────
    for interval in _INTERVALS:
        kline_resp = await client.get(
            "/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": _KLINE_LIMIT},
        )
        kline_resp.raise_for_status()
        raw = kline_resp.json()
        # Binance 캔들 포맷: [open_time, open, high, low, close, volume, ...]
        records = [
            {
                "timestamp": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in raw
        ]
        await redis.set(f"kline:{symbol}:{interval}:latest", json.dumps(records), ex=180)

    # ── 펀딩비 ────────────────────────────────────────────────────────────────
    try:
        funding_resp = await client.get(
            "/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": 1},
        )
        funding_resp.raise_for_status()
        funding_data = funding_resp.json()
        if funding_data:
            await redis.set(f"funding:{symbol}", json.dumps(funding_data[0]), ex=600)
    except Exception as exc:
        logger.warning("funding fetch failed symbol=%s: %s", symbol, exc)

    # ── 미결제 약정 ───────────────────────────────────────────────────────────
    try:
        oi_resp = await client.get("/fapi/v1/openInterest", params={"symbol": symbol})
        oi_resp.raise_for_status()
        await redis.set(f"oi:{symbol}", json.dumps(oi_resp.json()), ex=180)
    except Exception as exc:
        logger.warning("OI fetch failed symbol=%s: %s", symbol, exc)

    logger.info("market_data updated symbol=%s price=%s", symbol, price)
