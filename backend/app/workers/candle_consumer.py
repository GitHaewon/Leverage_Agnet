"""
Candle Close Consumer — Redis Streams에서 캔들 마감 이벤트를 소비해
OrchestratorPipeline을 트리거한다.

실행 방법:
  python -m app.workers.candle_consumer

스트림 구조:
  key:    candle:close
  fields: symbol (e.g. "BTCUSDT"), interval ("5m"), close_time (unix ms)

이 컨슈머는 별도 프로세스로 상시 실행된다. Celery worker와는 독립적이다.
"""
from __future__ import annotations

import asyncio
import logging
import signal as os_signal
from typing import NoReturn

import redis.asyncio as aioredis

from app.core.config import settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

STREAM_KEY = "candle:close"
CONSUMER_GROUP = "orchestrator-group"
CONSUMER_NAME = "candle-consumer-1"
BLOCK_MS = 5_000      # XREADGROUP block timeout (ms)
BATCH_SIZE = 10       # 한 번에 처리할 최대 메시지 수


async def _ensure_group(redis: aioredis.Redis) -> None:
    """컨슈머 그룹이 없으면 생성한다. 이미 존재하면 무시한다."""
    try:
        await redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="$", mkstream=True)
        logger.info("consumer group created: %s", CONSUMER_GROUP)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def _process_message(fields: dict[bytes, bytes], redis: aioredis.Redis) -> None:
    """
    단일 메시지를 처리한다.
    Celery 태스크를 enqueue하고 즉시 반환한다 (비동기 처리).
    """
    symbol = fields.get(b"symbol", b"BTCUSDT").decode()

    # close_price 필드가 있으면 Redis에 캐시한다 (shadow_monitor_worker 가격 조회용)
    raw_price = fields.get(b"close_price") or fields.get(b"close")
    if raw_price is not None:
        await redis.set(f"price:{symbol}", raw_price.decode(), ex=120)  # TTL 2분

    # 자동매매 활성 사용자 목록은 Celery 태스크 내부에서 조회한다
    celery_app.send_task(
        "app.workers.analysis_worker.run_analysis_cycle",
        args=([symbol],),
    )
    logger.debug("enqueued analysis for %s", symbol)


async def consume() -> NoReturn:
    """Redis Streams 메시지를 영속적으로 소비한다."""
    redis = aioredis.from_url(str(settings.REDIS_URL), decode_responses=False)
    await _ensure_group(redis)
    logger.info("candle consumer started, stream=%s group=%s", STREAM_KEY, CONSUMER_GROUP)

    while True:
        try:
            messages = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=BATCH_SIZE,
                block=BLOCK_MS,
            )
            if not messages:
                continue

            for _stream, entries in messages:
                for msg_id, fields in entries:
                    try:
                        await _process_message(fields, redis)
                        await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        # 개별 메시지 실패는 기록 후 계속 진행
                        # ACK하지 않으면 PEL에 남아 재처리된다
                        logger.exception("message processing error id=%s: %s", msg_id, exc)

        except asyncio.CancelledError:
            logger.info("candle consumer shutting down")
            await redis.aclose()
            return
        except Exception as exc:
            logger.exception("consumer loop error: %s", exc)
            await asyncio.sleep(5)


async def get_latest_prices() -> dict[str, float]:
    """
    Redis에 캐시된 심볼별 최신 종가를 반환한다.

    _process_message()가 캔들 마감 이벤트의 close_price 필드를 `price:{symbol}` 키로
    저장한다. shadow_monitor_worker가 이 함수로 현재가를 조회한다.

    캐시 미스(가격 없음)인 심볼은 결과에서 제외된다.
    """
    redis = aioredis.from_url(str(settings.REDIS_URL), decode_responses=True)
    try:
        symbols = ["BTCUSDT", "ETHUSDT"]
        prices: dict[str, float] = {}
        for symbol in symbols:
            val = await redis.get(f"price:{symbol}")
            if val is not None:
                prices[symbol] = float(val)
        return prices
    finally:
        await redis.aclose()


def _handle_shutdown(loop: asyncio.AbstractEventLoop) -> None:
    for task in asyncio.all_tasks(loop):
        task.cancel()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop = asyncio.new_event_loop()
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_shutdown, loop)
    try:
        loop.run_until_complete(consume())
    finally:
        loop.close()
