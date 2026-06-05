"""
MarketDataCollector — Binance Futures WebSocket 수집 메인 루프.

설계:
  - Combined Stream: 모든 심볼/인터벌을 하나의 연결로 구독
  - Auto-Reconnect: 지수 백오프 (1s → 2s → 4s → max 30s)
  - 재연결 후 누락 캔들 REST로 복구
  - HealthMonitor 백그라운드 Watchdog 병행 실행
  - REST 폴링 태스크 (OI/Funding) 병행 실행

WebSocket URL:
  Mainnet: wss://fstream.binance.com/stream?streams=<s1>/<s2>/...
  Testnet: wss://stream.binancefuture.com/stream?streams=...

구독 스트림 (2 symbols × 6 intervals + aggTrade + depth5):
  btcusdt@kline_1m, btcusdt@kline_5m, ..., btcusdt@aggTrade, btcusdt@depth5
  ethusdt@kline_1m, ..., ethusdt@aggTrade, ethusdt@depth5
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncContextManager, Callable

import redis.asyncio as aioredis
import websockets
import websockets.exceptions
from sqlalchemy.ext.asyncio import AsyncSession

from agents.market_data.health import HealthMonitor
from agents.market_data.models import (
    KLINE_INTERVALS,
    WS_BASE_MAINNET,
    WS_BASE_TESTNET,
    AggregateTrade,
    KlineData,
    OrderBookData,
)
from agents.market_data.normalizer import MarketDataNormalizer
from agents.market_data.publisher import MarketDataPublisher
from agents.market_data.rest_client import BinanceRestClient
from agents.market_data.storage import MarketDataStorage

logger = logging.getLogger(__name__)

DbFactory = Callable[[], AsyncContextManager[AsyncSession]]

# 지수 백오프 설정
_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 30.0
_BACKOFF_FACTOR = 2.0

# REST 폴링 주기 (초)
_REST_POLL_INTERVAL = 300  # 5분

# WebSocket 연결 옵션
_WS_PING_INTERVAL = 20       # 20초마다 Ping (Binance 서버 30초 타임아웃 방지)
_WS_PING_TIMEOUT = 10


@dataclass
class MarketDataConfig:
    """Market Data Agent 설정."""

    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    intervals: list[str] = field(default_factory=lambda: KLINE_INTERVALS)
    testnet: bool = False
    rest_poll_interval: int = _REST_POLL_INTERVAL


class MarketDataCollector:
    """
    Binance Futures WebSocket 수집기.

    사용법:
        cfg = MarketDataConfig(symbols=["BTCUSDT"], testnet=True)
        collector = MarketDataCollector(cfg, redis, db_factory)
        await collector.run_forever()
    """

    def __init__(
        self,
        config: MarketDataConfig,
        redis: aioredis.Redis,
        db_factory: DbFactory,
    ) -> None:
        self._config = config
        self._storage = MarketDataStorage(redis, db_factory)
        self._publisher = MarketDataPublisher(redis)
        self._health = HealthMonitor()
        self._normalizer = MarketDataNormalizer()
        self._rest = BinanceRestClient(testnet=config.testnet)

        self._ws_base = WS_BASE_TESTNET if config.testnet else WS_BASE_MAINNET
        self._backoff = _BACKOFF_INITIAL

        # 재연결 후 backfill을 위해 심볼별 마지막 캔들 수신 시간 추적
        self._last_kline_received: dict[str, dict[str, datetime]] = {
            sym: {} for sym in config.symbols
        }

    # ── 메인 루프 ─────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """WebSocket 메인 루프. 종료하려면 CancelledError를 발생시킨다."""
        await self._publisher.ensure_consumer_group()
        await self._health.start_watchdog()

        rest_task = asyncio.create_task(self._rest_polling_loop())

        try:
            while True:
                try:
                    await self._stream_once()
                    self._backoff = _BACKOFF_INITIAL  # 정상 종료 시 리셋
                except websockets.exceptions.WebSocketException as exc:
                    logger.warning(
                        "WebSocket error (backoff=%.1fs): %s", self._backoff, exc
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Unexpected error: %s", exc, exc_info=True)

                logger.info("Reconnecting in %.1fs ...", self._backoff)
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)

        finally:
            await self._health.stop_watchdog()
            rest_task.cancel()
            await self._rest.close()

    # ── WebSocket 단일 연결 세션 ──────────────────────────────────────────────

    async def _stream_once(self) -> None:
        url = self._build_stream_url()
        logger.info("Connecting to %s", url)

        async with websockets.connect(
            url,
            ping_interval=_WS_PING_INTERVAL,
            ping_timeout=_WS_PING_TIMEOUT,
            max_size=2**20,  # 1 MB
        ) as ws:
            logger.info("WebSocket connected ✓")
            self._backoff = _BACKOFF_INITIAL

            # 재연결 후 누락 데이터 복구
            await self._backfill_missing()

            async for raw_msg in ws:
                self._health.record_received()
                await self._dispatch(json.loads(raw_msg))

    # ── 이벤트 라우팅 ─────────────────────────────────────────────────────────

    async def _dispatch(self, event: dict) -> None:
        """Combined Stream 이벤트를 타입별로 핸들러에 라우팅."""
        # Combined Stream: {"stream": "btcusdt@kline_5m", "data": {...}}
        data = event.get("data", event)
        event_type = data.get("e", "")

        try:
            if event_type == "kline":
                await self._handle_kline(self._normalizer.parse_kline(data))
            elif event_type == "aggTrade":
                await self._handle_trade(self._normalizer.parse_agg_trade(data))
            elif event_type in ("depthUpdate", "depth"):
                await self._handle_depth(self._normalizer.parse_depth(data))
            else:
                logger.debug("Unknown event type: %s", event_type)
        except Exception as exc:
            logger.error("Dispatch error for event_type=%s: %s", event_type, exc)

    # ── Kline 핸들러 ──────────────────────────────────────────────────────────

    async def _handle_kline(self, kline: KlineData) -> None:
        # 항상: 현재가 캐시 + 최신 캔들 캐시 갱신
        await self._storage.cache_price(kline.as_price_data)
        await self._storage.cache_kline(kline)

        # 마지막 수신 시간 기록 (backfill 기준점)
        self._last_kline_received[kline.symbol][kline.interval] = datetime.now(timezone.utc)

        if kline.is_closed:
            logger.info(
                "Candle closed %s/%s close=%s volume=%s",
                kline.symbol, kline.interval, kline.close, kline.volume,
            )
            # TimescaleDB에 영구 저장
            await self._storage.persist_kline(kline)
            # 분석 파이프라인 트리거
            event = self._normalizer.kline_to_candle_event(kline)
            await self._publisher.publish_candle_close(event)

    # ── AggregateTrade 핸들러 ─────────────────────────────────────────────────

    async def _handle_trade(self, trade: AggregateTrade) -> None:
        # aggTrade는 현재가 업데이트에도 사용 (kline이 늦을 때 보완)
        from agents.market_data.models import PriceData
        price_data = PriceData(
            symbol=trade.symbol,
            coin=trade.coin,
            price=trade.price,
        )
        await self._storage.cache_price(price_data)

    # ── OrderBook 핸들러 ──────────────────────────────────────────────────────

    async def _handle_depth(self, book: OrderBookData) -> None:
        await self._storage.cache_orderbook(book)

    # ── REST 폴링 루프 (OI / Funding) ─────────────────────────────────────────

    async def _rest_polling_loop(self) -> None:
        """OI + Funding Rate 5분 주기 폴링 (별도 태스크)."""
        while True:
            await asyncio.sleep(self._config.rest_poll_interval)
            for symbol in self._config.symbols:
                await self._fetch_and_cache_rest(symbol)

    async def _fetch_and_cache_rest(self, symbol: str) -> None:
        funding, oi = await self._rest.get_funding_and_oi(symbol)
        if funding:
            await self._storage.cache_funding(funding)
            logger.debug("Funding cached %s: %s", symbol, funding.funding_rate)
        if oi:
            await self._storage.cache_open_interest(oi)
            logger.debug("OI cached %s: %s", symbol, oi.open_interest)

    # ── 누락 캔들 복구 (Backfill) ─────────────────────────────────────────────

    async def _backfill_missing(self) -> None:
        """
        WebSocket 재연결 후 누락 캔들을 REST로 복구한다.
        마지막 수신 시간 이후의 캔들을 조회하여 DB에 저장.
        """
        for symbol in self._config.symbols:
            for interval in self._config.intervals:
                last_time = self._last_kline_received.get(symbol, {}).get(interval)
                if last_time is None:
                    # 최초 연결 — DB에서 마지막 시간 조회
                    coin = symbol.replace("USDT", "")
                    last_time = await self._storage.get_latest_kline_time(coin, interval)

                if last_time is None:
                    continue  # DB에도 없으면 현재부터 시작

                klines = await self._rest.get_klines(symbol, interval, since=last_time)
                if klines:
                    saved = await self._storage.bulk_persist_klines(klines)
                    logger.info(
                        "Backfill %s/%s: saved %d candles",
                        symbol, interval, saved,
                    )

    # ── WebSocket URL 빌드 ────────────────────────────────────────────────────

    def _build_stream_url(self) -> str:
        """
        Combined Stream URL 구성.

        예: wss://fstream.binance.com/stream?streams=
              btcusdt@kline_1m/btcusdt@kline_5m/.../btcusdt@aggTrade/btcusdt@depth5/
              ethusdt@kline_1m/.../ethusdt@depth5
        """
        streams: list[str] = []
        for symbol in self._config.symbols:
            sym_lower = symbol.lower()
            for interval in self._config.intervals:
                streams.append(f"{sym_lower}@kline_{interval}")
            streams.append(f"{sym_lower}@aggTrade")
            streams.append(f"{sym_lower}@depth5")

        return f"{self._ws_base}?streams={'/' .join(streams)}"

    # ── 상태 조회 ─────────────────────────────────────────────────────────────

    def get_health_status(self) -> dict:
        return {
            "websocket": self._health.get_status(),
            "symbols": self._config.symbols,
            "testnet": self._config.testnet,
        }
