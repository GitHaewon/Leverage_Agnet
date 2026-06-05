"""app/utils/exceptions.py 단위 테스트."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from fastapi import APIRouter

from app.utils.exceptions import (
    AppError,
    BillingError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TradingHaltedError,
    UnauthorizedError,
)


class TestAppErrorAttributes:
    def test_base_app_error_defaults(self) -> None:
        err = AppError(code="TEST_001", message="테스트 오류")
        assert err.code == "TEST_001"
        assert err.message == "테스트 오류"
        assert err.status_code == 400
        assert err.detail == {}

    def test_not_found_error(self) -> None:
        err = NotFoundError("Signal")
        assert err.code == "NOT_FOUND_001"
        assert err.status_code == 404
        assert "Signal" in err.message

    def test_unauthorized_error_default(self) -> None:
        err = UnauthorizedError()
        assert err.status_code == 401
        assert err.code == "AUTH_004"

    def test_unauthorized_error_custom_code(self) -> None:
        err = UnauthorizedError(code="AUTH_002", message="이메일 인증 필요")
        assert err.code == "AUTH_002"

    def test_forbidden_error(self) -> None:
        err = ForbiddenError()
        assert err.status_code == 403
        assert err.code == "AUTH_005"

    def test_conflict_error(self) -> None:
        err = ConflictError(code="AUTH_006", message="이미 가입된 이메일")
        assert err.status_code == 409

    def test_billing_error(self) -> None:
        err = BillingError()
        assert err.status_code == 403
        assert err.code == "BILLING_001"

    def test_trading_halted_error(self) -> None:
        err = TradingHaltedError("일일 손실 한도 도달")
        assert err.status_code == 400
        assert err.code == "ORDER_001"
        assert err.detail["halt_reason"] == "일일 손실 한도 도달"


class TestExceptionHandlers:
    async def test_app_error_returns_correct_structure(self, client: AsyncClient) -> None:
        from app.main import app
        from app.utils.exceptions import NotFoundError

        test_router = APIRouter()

        @test_router.get("/test-not-found-exc")
        async def _raise():
            raise NotFoundError("포지션")

        app.include_router(test_router, prefix="/api/v1")
        response = await client.get("/api/v1/test-not-found-exc")

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "NOT_FOUND_001"
        assert "error" in body
        assert "meta" in body
        assert body["meta"]["request_id"].startswith("req_")

    async def test_validation_error_422(self, client: AsyncClient) -> None:
        from app.main import app
        from pydantic import BaseModel

        class _Input(BaseModel):
            value: int

        test_router = APIRouter()

        @test_router.post("/test-validation-exc")
        async def _validate(body: _Input):
            return body

        app.include_router(test_router, prefix="/api/v1")
        response = await client.post(
            "/api/v1/test-validation-exc",
            json={"value": "not_a_number"},
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_001"
        assert "fields" in body["error"]["detail"]

    async def test_unhandled_exception_returns_500(self, client: AsyncClient) -> None:
        from app.main import app

        test_router = APIRouter()

        @test_router.get("/test-unhandled-exc")
        async def _raise():
            raise RuntimeError("Unexpected crash")

        app.include_router(test_router, prefix="/api/v1")
        response = await client.get("/api/v1/test-unhandled-exc")

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "SERVER_001"

    async def test_404_not_found_route(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/nonexistent-route-xyz")
        assert response.status_code == 404


class TestSecurityExceptions:
    async def test_unauthorized_returns_401(self, client: AsyncClient) -> None:
        from app.main import app
        from app.utils.exceptions import UnauthorizedError

        test_router = APIRouter()

        @test_router.get("/test-auth-exc")
        async def _raise():
            raise UnauthorizedError()

        app.include_router(test_router, prefix="/api/v1")
        response = await client.get("/api/v1/test-auth-exc")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_004"

    async def test_forbidden_returns_403(self, client: AsyncClient) -> None:
        from app.main import app
        from app.utils.exceptions import BillingError

        test_router = APIRouter()

        @test_router.get("/test-billing-exc")
        async def _raise():
            raise BillingError()

        app.include_router(test_router, prefix="/api/v1")
        response = await client.get("/api/v1/test-billing-exc")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "BILLING_001"
