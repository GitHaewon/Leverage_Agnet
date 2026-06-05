from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import DbDep, RedisDep
from app.core.config import settings
from app.schemas.common import DataResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class ServiceStatus(BaseModel):
    status: str                          # "healthy" | "unhealthy"
    latency_ms: float | None = None
    error: str | None = None


class HealthData(BaseModel):
    status: str                          # "healthy" | "degraded"
    version: str
    environment: str
    timestamp: str
    services: dict[str, ServiceStatus]


@router.get(
    "/health",
    response_model=DataResponse[HealthData],
    summary="서비스 헬스 체크",
    description="PostgreSQL, Redis 연결 상태를 확인하고 전체 서비스 상태를 반환합니다.",
)
async def health_check(db: DbDep, redis: RedisDep) -> DataResponse[HealthData]:
    services: dict[str, ServiceStatus] = {}
    all_healthy = True

    # ── PostgreSQL ──────────────────────────────────────────────────────────────
    try:
        t = time.monotonic()
        await db.execute(text("SELECT 1"))
        services["postgresql"] = ServiceStatus(
            status="healthy",
            latency_ms=round((time.monotonic() - t) * 1000, 2),
        )
    except Exception as exc:
        logger.error("PostgreSQL health check failed: %s", exc)
        services["postgresql"] = ServiceStatus(status="unhealthy", error=str(exc))
        all_healthy = False

    # ── Redis ───────────────────────────────────────────────────────────────────
    try:
        t = time.monotonic()
        await redis.ping()
        services["redis"] = ServiceStatus(
            status="healthy",
            latency_ms=round((time.monotonic() - t) * 1000, 2),
        )
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        services["redis"] = ServiceStatus(status="unhealthy", error=str(exc))
        all_healthy = False

    return DataResponse(
        data=HealthData(
            status="healthy" if all_healthy else "degraded",
            version=settings.APP_VERSION,
            environment=settings.APP_ENV,
            timestamp=datetime.now(timezone.utc).isoformat(),
            services=services,
        )
    )
