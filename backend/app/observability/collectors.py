"""
백그라운드 메트릭 수집기.

Gauge 타입 메트릭처럼 '현재 상태'를 주기적으로 스냅샷해야 하는 값들을 수집한다.
- Celery 큐 길이 (Redis LLEN)

PnL, Drawdown, Balance는 서비스 레이어에서 이벤트 발생 시 직접 갱신하므로
여기서는 수집하지 않는다.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_CELERY_QUEUES = ["celery", "analysis", "notifications"]
_POLL_INTERVAL_SECONDS = 30


async def _collect_queue_lengths(redis_client: object) -> None:
    """Redis에서 Celery 큐 길이를 읽어 Gauge에 기록한다."""
    from app.observability.metrics import CELERY_QUEUE_LENGTH

    for queue in _CELERY_QUEUES:
        try:
            length = await redis_client.llen(queue)  # type: ignore[attr-defined]
            CELERY_QUEUE_LENGTH.labels(queue=queue).set(length or 0)
        except Exception as exc:
            logger.debug("queue_length_collect_failed queue=%s err=%s", queue, exc)


async def run_collector() -> None:
    """
    백그라운드 수집 루프.
    FastAPI lifespan에서 asyncio.create_task()로 실행한다.
    """
    from app.core.redis_client import get_redis

    logger.info("Observability collector started (interval=%ds)", _POLL_INTERVAL_SECONDS)

    while True:
        try:
            redis = await get_redis()
            await _collect_queue_lengths(redis)
        except Exception as exc:
            logger.debug("collector_cycle_failed err=%s", exc)

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
