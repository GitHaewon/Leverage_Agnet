"""
candle_consumer 가격 캐시 + get_latest_prices() 검증.

검증 항목:
  1. _process_message()에 close_price 필드가 있으면 Redis에 캐시된다
  2. _process_message()에 close 필드(대안)가 있으면 Redis에 캐시된다
  3. 가격 필드가 없으면 Redis 쓰기를 하지 않는다
  4. get_latest_prices()는 캐시된 가격을 반환한다
  5. get_latest_prices()는 캐시 미스 심볼을 결과에서 제외한다
  6. get_latest_prices()는 캐시가 없으면 빈 dict를 반환한다
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# celery + config: 테스트 환경 미설치 대비 사전 모킹
_celery_stub = MagicMock()
sys.modules.setdefault("celery", _celery_stub)
sys.modules.setdefault("celery.signals", MagicMock())
_config_stub = MagicMock()
_config_stub.settings.REDIS_URL = "redis://localhost:6379/0"
if "app.core.config" not in sys.modules:
    sys.modules["app.core.config"] = _config_stub
if "app.workers.celery_app" not in sys.modules:
    sys.modules["app.workers.celery_app"] = MagicMock()

from app.workers.candle_consumer import _process_message, get_latest_prices  # noqa: E402


# ── _process_message 가격 캐시 ───────────────────────────────────────────────

class TestProcessMessagePriceCache:

    @pytest.mark.asyncio
    async def test_close_price_field_writes_to_redis(self):
        """close_price 필드 → redis.set() 호출."""
        mock_redis = AsyncMock()
        fields = {
            b"symbol": b"BTCUSDT",
            b"close_price": b"67500.00",
        }
        await _process_message(fields, mock_redis)
        mock_redis.set.assert_awaited_once_with("price:BTCUSDT", "67500.00", ex=120)

    @pytest.mark.asyncio
    async def test_close_field_fallback_writes_to_redis(self):
        """close 필드(대안 키) → redis.set() 호출."""
        mock_redis = AsyncMock()
        fields = {
            b"symbol": b"ETHUSDT",
            b"close": b"3500.00",
        }
        await _process_message(fields, mock_redis)
        mock_redis.set.assert_awaited_once_with("price:ETHUSDT", "3500.00", ex=120)

    @pytest.mark.asyncio
    async def test_no_price_field_skips_redis_write(self):
        """가격 필드 없음 → redis.set() 호출 안 됨."""
        mock_redis = AsyncMock()
        fields = {
            b"symbol": b"BTCUSDT",
            b"interval": b"5m",
            b"close_time": b"1717000000000",
        }
        await _process_message(fields, mock_redis)
        mock_redis.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_celery_task_always_enqueued(self):
        """가격 필드 유무와 무관하게 Celery task는 항상 enqueue된다."""
        import app.workers.candle_consumer as module
        mock_celery = MagicMock()
        mock_redis = AsyncMock()

        original = module.celery_app
        module.celery_app = mock_celery
        try:
            await _process_message({b"symbol": b"BTCUSDT"}, mock_redis)
        finally:
            module.celery_app = original

        mock_celery.send_task.assert_called_once()


# ── get_latest_prices ────────────────────────────────────────────────────────

class TestGetLatestPrices:

    @pytest.mark.asyncio
    async def test_returns_cached_prices(self):
        """Redis에 캐시된 가격을 float dict로 반환한다."""
        async def fake_get(key):
            return {"price:BTCUSDT": "67500.0", "price:ETHUSDT": "3500.0"}.get(key)

        mock_redis = AsyncMock()
        mock_redis.get.side_effect = fake_get
        mock_redis_cls = MagicMock(return_value=mock_redis)

        with patch("app.workers.candle_consumer.aioredis.from_url", mock_redis_cls):
            result = await get_latest_prices()

        assert result == {"BTCUSDT": 67500.0, "ETHUSDT": 3500.0}

    @pytest.mark.asyncio
    async def test_excludes_cache_miss_symbols(self):
        """캐시 미스 심볼은 결과에서 제외된다."""
        async def fake_get(key):
            return "67500.0" if key == "price:BTCUSDT" else None

        mock_redis = AsyncMock()
        mock_redis.get.side_effect = fake_get

        with patch("app.workers.candle_consumer.aioredis.from_url", MagicMock(return_value=mock_redis)):
            result = await get_latest_prices()

        assert "BTCUSDT" in result
        assert "ETHUSDT" not in result

    @pytest.mark.asyncio
    async def test_empty_dict_when_no_cache(self):
        """캐시가 전혀 없으면 빈 dict를 반환한다 (크래시 없음)."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("app.workers.candle_consumer.aioredis.from_url", MagicMock(return_value=mock_redis)):
            result = await get_latest_prices()

        assert result == {}
