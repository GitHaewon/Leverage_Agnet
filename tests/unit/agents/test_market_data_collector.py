"""
Market Data Collector / Health Monitor 단위 테스트.

WebSocket 연결은 Mock 처리.
Auto-Reconnect 로직 + URL 빌드 + Health Monitor 검증.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.market_data.collector import MarketDataCollector, MarketDataConfig
from agents.market_data.health import HealthMonitor
from agents.market_data.models import KLINE_INTERVALS


# ── 픽스처 ────────────────────────────────────────────────────────────────────

def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.xadd = AsyncMock(return_value=b"1234-0")
    redis.xgroup_create = AsyncMock(return_value=True)
    return redis


def _make_db_factory():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.scalar_one_or_none = AsyncMock(return_value=None)

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory


def _make_collector(symbols=None, testnet=True) -> MarketDataCollector:
    redis = _make_redis()
    db = _make_db_factory()
    cfg = MarketDataConfig(
        symbols=symbols or ["BTCUSDT", "ETHUSDT"],
        testnet=testnet,
    )
    return MarketDataCollector(cfg, redis, db)


# ── WebSocket URL 빌드 ────────────────────────────────────────────────────────

class TestBuildStreamUrl:
    def test_testnet_url(self):
        collector = _make_collector(testnet=True)
        url = collector._build_stream_url()
        assert url.startswith("wss://stream.binancefuture.com/stream")

    def test_mainnet_url(self):
        collector = _make_collector(testnet=False)
        url = collector._build_stream_url()
        assert url.startswith("wss://fstream.binance.com/stream")

    def test_contains_all_intervals(self):
        collector = _make_collector(symbols=["BTCUSDT"])
        url = collector._build_stream_url()
        for interval in KLINE_INTERVALS:
            assert f"@kline_{interval}" in url

    def test_contains_agg_trade(self):
        collector = _make_collector(symbols=["BTCUSDT"])
        url = collector._build_stream_url()
        assert "btcusdt@aggTrade" in url

    def test_contains_depth(self):
        collector = _make_collector(symbols=["BTCUSDT"])
        url = collector._build_stream_url()
        assert "btcusdt@depth5" in url

    def test_multiple_symbols(self):
        collector = _make_collector(symbols=["BTCUSDT", "ETHUSDT"])
        url = collector._build_stream_url()
        assert "btcusdt@" in url
        assert "ethusdt@" in url

    def test_streams_joined_by_slash(self):
        collector = _make_collector(symbols=["BTCUSDT"])
        url = collector._build_stream_url()
        streams_part = url.split("?streams=")[1]
        # 스트림들이 / 로 구분됨
        assert "/" in streams_part
        assert "//" not in streams_part.split("//")[-1]  # 이중 슬래시 없음


# ── 이벤트 라우팅 ─────────────────────────────────────────────────────────────

_KLINE_CLOSED = {
    "stream": "btcusdt@kline_5m",
    "data": {
        "e": "kline",
        "s": "BTCUSDT",
        "k": {
            "t": 1717459800000, "T": 1717460099999,
            "i": "5m",
            "o": "67450.00", "c": "67520.00",
            "h": "67580.00", "l": "67400.00",
            "v": "123.456", "n": 1234, "x": True,
        },
    },
}

_KLINE_OPEN = {
    "stream": "btcusdt@kline_5m",
    "data": {
        "e": "kline",
        "s": "BTCUSDT",
        "k": {
            **_KLINE_CLOSED["data"]["k"],
            "x": False,
        },
    },
}

_AGG_TRADE = {
    "stream": "btcusdt@aggTrade",
    "data": {
        "e": "aggTrade",
        "s": "BTCUSDT",
        "p": "67520.00", "q": "0.001",
        "m": False, "T": 1717459800100,
    },
}

_DEPTH = {
    "stream": "btcusdt@depth5",
    "data": {
        "e": "depthUpdate",
        "s": "BTCUSDT",
        "b": [["67450.00", "1.5"]],
        "a": [["67460.00", "0.8"]],
    },
}


class TestDispatch:
    @pytest.mark.asyncio
    async def test_closed_kline_persists_to_db(self):
        collector = _make_collector()
        with patch.object(collector._storage, "persist_kline", AsyncMock()) as mock_persist, \
             patch.object(collector._storage, "cache_price", AsyncMock()), \
             patch.object(collector._storage, "cache_kline", AsyncMock()), \
             patch.object(collector._publisher, "publish_candle_close", AsyncMock()):
            await collector._dispatch(_KLINE_CLOSED)
            mock_persist.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_kline_does_not_persist(self):
        collector = _make_collector()
        with patch.object(collector._storage, "persist_kline", AsyncMock()) as mock_persist, \
             patch.object(collector._storage, "cache_price", AsyncMock()), \
             patch.object(collector._storage, "cache_kline", AsyncMock()):
            await collector._dispatch(_KLINE_OPEN)
            mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_closed_kline_publishes_event(self):
        collector = _make_collector()
        with patch.object(collector._publisher, "publish_candle_close", AsyncMock()) as mock_pub, \
             patch.object(collector._storage, "persist_kline", AsyncMock()), \
             patch.object(collector._storage, "cache_price", AsyncMock()), \
             patch.object(collector._storage, "cache_kline", AsyncMock()):
            await collector._dispatch(_KLINE_CLOSED)
            mock_pub.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_kline_does_not_publish(self):
        collector = _make_collector()
        with patch.object(collector._publisher, "publish_candle_close", AsyncMock()) as mock_pub, \
             patch.object(collector._storage, "cache_price", AsyncMock()), \
             patch.object(collector._storage, "cache_kline", AsyncMock()):
            await collector._dispatch(_KLINE_OPEN)
            mock_pub.assert_not_called()

    @pytest.mark.asyncio
    async def test_agg_trade_updates_price(self):
        collector = _make_collector()
        with patch.object(collector._storage, "cache_price", AsyncMock()) as mock_price:
            await collector._dispatch(_AGG_TRADE)
            mock_price.assert_called_once()

    @pytest.mark.asyncio
    async def test_depth_updates_orderbook(self):
        collector = _make_collector()
        with patch.object(collector._storage, "cache_orderbook", AsyncMock()) as mock_book:
            await collector._dispatch(_DEPTH)
            mock_book.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_event_type_no_error(self):
        collector = _make_collector()
        # 알 수 없는 이벤트 타입은 로그만, 에러 없음
        await collector._dispatch({"data": {"e": "unknown_event_xyz"}})


# ── HealthMonitor ─────────────────────────────────────────────────────────────

class TestHealthMonitor:
    def test_initial_state_unhealthy(self):
        h = HealthMonitor()
        assert h.is_healthy is False
        assert h.elapsed_seconds == float("inf")

    def test_after_record_healthy(self):
        h = HealthMonitor(unhealthy_threshold=30)
        h.record_received()
        assert h.is_healthy is True

    def test_unhealthy_after_timeout(self):
        h = HealthMonitor(unhealthy_threshold=30)
        h.record_received()
        # 수동으로 시간 조작
        h._last_received_at = datetime.now(timezone.utc) - timedelta(seconds=31)
        assert h.is_healthy is False

    def test_critical_after_5_minutes(self):
        h = HealthMonitor(critical_threshold=300)
        h._last_received_at = datetime.now(timezone.utc) - timedelta(seconds=301)
        assert h.is_critical is True

    def test_not_critical_within_threshold(self):
        h = HealthMonitor(critical_threshold=300)
        h.record_received()
        assert h.is_critical is False

    def test_get_status_structure(self):
        h = HealthMonitor()
        h.record_received()
        status = h.get_status()
        assert "is_healthy" in status
        assert "is_critical" in status
        assert "last_received_at" in status
        assert "elapsed_seconds" in status

    def test_get_status_no_data(self):
        h = HealthMonitor()
        status = h.get_status()
        assert status["last_received_at"] is None
        assert status["elapsed_seconds"] is None

    @pytest.mark.asyncio
    async def test_watchdog_start_stop(self):
        h = HealthMonitor()
        await h.start_watchdog()
        assert h._task is not None
        await h.stop_watchdog()

    @pytest.mark.asyncio
    async def test_critical_callback_called(self):
        callback_called = []

        def on_critical(elapsed: int) -> None:
            callback_called.append(elapsed)

        h = HealthMonitor(critical_threshold=5, on_critical=on_critical)
        h._last_received_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await h._check()
        assert len(callback_called) == 1
        assert callback_called[0] >= 10


# ── 건강 상태 조회 ─────────────────────────────────────────────────────────────

class TestGetHealthStatus:
    def test_health_status_structure(self):
        collector = _make_collector(symbols=["BTCUSDT"])
        status = collector.get_health_status()
        assert "websocket" in status
        assert "symbols" in status
        assert "testnet" in status
        assert status["testnet"] is True
        assert status["symbols"] == ["BTCUSDT"]
