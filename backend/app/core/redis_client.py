from __future__ import annotations

import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def connect_redis() -> None:
    """앱 시작 시 Redis 연결. lifespan에서 호출."""
    global _redis
    _redis = aioredis.from_url(
        str(settings.REDIS_URL),
        encoding="utf-8",
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        protocol=2,
    )
    await _redis.ping()
    logger.info("Redis connected: %s", _safe_url(str(settings.REDIS_URL)))


async def disconnect_redis() -> None:
    """앱 종료 시 Redis 연결 해제. lifespan에서 호출."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Redis disconnected")


def get_redis() -> aioredis.Redis:
    """FastAPI 의존성: 전역 Redis 클라이언트 반환."""
    if _redis is None:
        raise RuntimeError("Redis is not connected. Ensure connect_redis() was called.")
    return _redis


def _safe_url(url: str) -> str:
    """로그 출력용: 비밀번호 마스킹."""
    if "@" in url:
        scheme_and_auth, rest = url.split("@", 1)
        if ":" in scheme_and_auth.split("//")[-1]:
            scheme = scheme_and_auth.split("//")[0]
            host = scheme_and_auth.split("//")[1].split(":")[0]
            return f"{scheme}//{host}:****@{rest}"
    return url
