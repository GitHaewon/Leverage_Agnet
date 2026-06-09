from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.redis_client import connect_redis, disconnect_redis
from app.observability.collectors import run_collector
from app.observability.middleware import PrometheusMiddleware
from app.utils.exceptions import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.utils.logging import setup_logging
from app.utils.middleware import RequestLoggingMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ────────────────────────────────────────────────────────────────
    setup_logging()
    logger.info(
        "Starting %s v%s [%s]",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.APP_ENV,
    )

    await connect_redis()

    # Prometheus 백그라운드 수집기 시작
    collector_task = asyncio.create_task(run_collector())

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    collector_task.cancel()
    await disconnect_redis()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Binance Futures 특화 AI 트레이딩 SaaS",
        # 프로덕션에서 Swagger UI 비활성화 (정보 노출 방지)
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────────────────────────
    # 순서 중요: 마지막에 추가된 미들웨어가 가장 먼저 실행됨 (LIFO)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(PrometheusMiddleware)   # HTTP 메트릭 수집 (RequestLogging보다 외부에서 실행)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception Handlers ─────────────────────────────────────────────────────
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ── Routers ────────────────────────────────────────────────────────────────
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
