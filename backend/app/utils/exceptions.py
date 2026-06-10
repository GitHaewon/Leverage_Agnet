from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorDetail, ErrorResponse, Meta

logger = logging.getLogger(__name__)


# ── 커스텀 예외 클래스 ─────────────────────────────────────────────────────────

class AppError(Exception):
    """모든 앱 예외의 베이스. API 에러 코드와 HTTP 상태 코드를 포함."""
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str) -> None:
        super().__init__(
            code="NOT_FOUND_001",
            message=f"요청한 리소스를 찾을 수 없습니다: {resource}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class UnauthorizedError(AppError):
    def __init__(
        self,
        code: str = "AUTH_004",
        message: str = "토큰이 만료되었거나 유효하지 않습니다.",
    ) -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(AppError):
    def __init__(
        self,
        code: str = "AUTH_005",
        message: str = "접근 권한이 없습니다.",
    ) -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN)


class ConflictError(AppError):
    def __init__(
        self,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


class BillingError(AppError):
    def __init__(self, code: str = "BILLING_001", message: str = "플랜 업그레이드가 필요합니다.") -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN)


class TradingHaltedError(AppError):
    """일일 손실 한도 등으로 자동매매가 중단된 경우."""
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="ORDER_001",
            message=f"자동매매가 중단된 상태입니다: {reason}",
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"halt_reason": reason},
        )


# ── 에러 응답 빌더 ─────────────────────────────────────────────────────────────

def _build_error_response(
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ErrorResponse(
        error=ErrorDetail(code=code, message=message, detail=detail or {}),
        meta=Meta(),
    ).model_dump()


# ── FastAPI 예외 핸들러 ────────────────────────────────────────────────────────

async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error(
            "Application error",
            extra={"code": exc.code, "path": str(request.url), "detail": exc.detail},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error_response(exc.code, exc.message, exc.detail),
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error_response("HTTP_ERROR", str(exc.detail)),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields: dict[str, str] = {}
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        fields[field] = error["msg"]

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_build_error_response(
            "VALIDATION_001",
            "입력 값이 올바르지 않습니다.",
            {"fields": fields},
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception", extra={"path": str(request.url)})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_build_error_response("SERVER_001", "서버 내부 오류가 발생했습니다."),
    )
