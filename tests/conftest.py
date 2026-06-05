"""
최상위 conftest.py — pytest가 테스트 파일을 수집하기 전에 실행됨.
모듈 레벨 os.environ 설정으로 Settings() 초기화 전에 환경변수를 주입한다.
"""
from __future__ import annotations

import os

# ── 테스트 환경변수 주입 (Settings() import 전에 실행되어야 함) ──────────────
_TEST_ENV: dict[str, str] = {
    "APP_ENV": "testing",
    "DEBUG": "false",
    "DATABASE_URL": "postgresql://trading:trading_pass@localhost:5432/trading_test",
    "REDIS_URL": "redis://localhost:6379/15",
    "JWT_SECRET": "test-jwt-secret-key-minimum-32-characters!!",
    "JWT_REFRESH_SECRET": "test-refresh-secret-minimum-32-characters!",
    "BINANCE_TESTNET": "true",
    "BINANCE_ENCRYPT_KEY": "0123456789abcdef0123456789abcdef",   # 32 hex chars
    "ANTHROPIC_API_KEY": "sk-ant-test-placeholder",
    "CLAUDE_MODEL": "claude-sonnet-4-6",
    "STRIPE_SECRET_KEY": "sk_test_placeholder",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_placeholder",
    "TELEGRAM_BOT_TOKEN": "1234567890:AABBCCDDEEFFaabbccddeeff_test",
    "CORS_ORIGINS": "http://localhost:3000",
}

for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock, MagicMock

from app.models.base import Base


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """테스트용 인메모리 SQLite 엔진 (PostgreSQL 호환 기능 제외)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    """테스트용 DB 세션."""
    Session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest.fixture
def mock_redis():
    """Redis Mock — 단위 테스트용."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.exists = AsyncMock(return_value=0)
    mock.expire = AsyncMock(return_value=True)
    return mock


@pytest_asyncio.fixture
async def client(db_session, mock_redis):
    """FastAPI 테스트 클라이언트 — DB와 Redis를 Mock으로 교체."""
    from app.main import app
    from app.core.database import get_db
    from app.core.redis_client import get_redis

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = lambda: mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
