"""
MarketDataPublisher — Redis Streams 이벤트 발행.

발행 스트림:
  stream:analysis_trigger — 캔들 완성 시 분석 파이프라인 트리거
    fields: event, coin, symbol, interval, close_price, close_time

설계:
  - Redis Streams XADD 사용 (Consumer Group 패턴으로 소비)
  - 각 스트림은 maxlen=1000으로 자동 트리밍 (메모리 제어)
  - 발행 실패는 로그만 (분석 파이프라인에 영향 주지 않도록)
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

from agents.market_data.models import CandleCloseEvent, STREAM_ANALYSIS_TRIGGER

logger = logging.getLogger(__name__)

_STREAM_MAXLEN = 1000  # 스트림 최대 메시지 수 (자동 트리밍)


class MarketDataPublisher:
    """Redis Streams 이벤트 발행자."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def publish_candle_close(self, event: CandleCloseEvent) -> str | None:
        """
        캔들 완성 이벤트를 Redis Streams에 발행한다.

        Returns:
            Redis message ID (str) | None (발행 실패)
        """
        try:
            msg_id = await self._redis.xadd(
                STREAM_ANALYSIS_TRIGGER,
                event.to_stream_dict(),
                maxlen=_STREAM_MAXLEN,
                approximate=True,  # ~ (approximate trimming, 성능 우선)
            )
            logger.debug(
                "Published candle_close %s/%s interval=%s price=%s id=%s",
                event.coin, event.symbol, event.interval, event.close_price, msg_id,
            )
            return msg_id
        except Exception as exc:
            logger.error(
                "Failed to publish candle_close %s/%s: %s",
                event.coin, event.interval, exc,
            )
            return None

    async def ensure_consumer_group(self) -> None:
        """
        Consumer Group이 없으면 생성한다.
        앱 시작 시 1회 호출.

        Group 이름: analysis_pipeline
        """
        try:
            await self._redis.xgroup_create(
                STREAM_ANALYSIS_TRIGGER,
                "analysis_pipeline",
                id="0",       # 모든 메시지부터 소비
                mkstream=True,  # 스트림이 없으면 생성
            )
            logger.info("Created consumer group 'analysis_pipeline' on %s", STREAM_ANALYSIS_TRIGGER)
        except Exception as exc:
            # BUSYGROUP = 이미 존재 → 정상
            if "BUSYGROUP" not in str(exc):
                logger.warning("xgroup_create: %s", exc)
