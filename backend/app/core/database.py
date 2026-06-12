from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(
    settings.async_database_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,          # 끊긴 연결 자동 재연결
    echo=settings.DB_ECHO,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,      # commit 후에도 attribute access 허용
    autoflush=False,
    autocommit=False,
)


@asynccontextmanager
async def celery_session():
    """Celery 태스크 전용 세션. NullPool로 event loop 경계 문제를 방지한다."""
    _engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    _factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False, autoflush=False, autocommit=False
    )
    try:
        async with _factory() as session:
            yield session
    finally:
        await _engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성: 요청당 하나의 DB 세션."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
