"""GET /api/v1/health 단위 테스트."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession


class TestHealthCheck:
    async def test_returns_200_when_all_healthy(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200

    async def test_response_has_data_and_meta(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/health")).json()
        assert "data" in body
        assert "meta" in body

    async def test_status_is_healthy_when_all_up(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/health")).json()
        assert body["data"]["status"] == "healthy"

    async def test_services_include_postgresql_and_redis(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/health")).json()
        services = body["data"]["services"]
        assert "postgresql" in services
        assert "redis" in services

    async def test_postgresql_shows_latency(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/health")).json()
        pg = body["data"]["services"]["postgresql"]
        assert pg["status"] == "healthy"
        assert pg["latency_ms"] is not None
        assert pg["latency_ms"] >= 0

    async def test_meta_has_request_id_and_timestamp(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/health")).json()
        assert body["meta"]["request_id"].startswith("req_")
        assert "T" in body["meta"]["timestamp"]   # ISO 8601 확인

    async def test_degraded_when_db_fails(
        self, mock_redis: AsyncMock, db_session: AsyncSession
    ) -> None:
        """DB 연결 실패 시 status=degraded, HTTP는 여전히 200."""
        from app.main import app
        from app.core.database import get_db
        from app.core.redis_client import get_redis

        broken_db = AsyncMock(spec=AsyncSession)
        broken_db.execute.side_effect = Exception("Connection refused")

        async def _broken_db():
            yield broken_db

        app.dependency_overrides[get_db] = _broken_db
        app.dependency_overrides[get_redis] = lambda: mock_redis

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/health")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "degraded"
        assert body["data"]["services"]["postgresql"]["status"] == "unhealthy"
        assert body["data"]["services"]["redis"]["status"] == "healthy"

    async def test_degraded_when_redis_fails(
        self, db_session: AsyncSession
    ) -> None:
        """Redis 연결 실패 시 status=degraded."""
        from app.main import app
        from app.core.database import get_db
        from app.core.redis_client import get_redis

        broken_redis = AsyncMock()
        broken_redis.ping.side_effect = Exception("Redis unavailable")

        async def _db():
            yield db_session

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_redis] = lambda: broken_redis

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/health")

        app.dependency_overrides.clear()

        body = response.json()
        assert body["data"]["status"] == "degraded"
        assert body["data"]["services"]["redis"]["status"] == "unhealthy"

    async def test_response_includes_version_and_env(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/health")).json()
        data = body["data"]
        assert data["version"] == "0.1.0"
        assert data["environment"] == "testing"
        assert data["timestamp"]
