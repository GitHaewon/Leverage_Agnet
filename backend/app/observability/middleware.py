"""
HTTP 요청 메트릭 미들웨어.

모든 HTTP 요청의 횟수와 지연 시간을 자동으로 기록한다.
기존 RequestLoggingMiddleware와 함께 체이닝한다.
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability import metrics

# 메트릭을 기록하지 않을 경로
_SKIP_PATHS = frozenset({
    "/metrics",
    "/api/v1/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
})

# 고유 user_id가 들어간 경로는 파라미터로 정규화
_PATH_NORMALIZE = {
    # 예: /api/v1/users/abc-123 → /api/v1/users/{id}
}


def _normalize_path(path: str) -> str:
    """
    UUID/숫자 세그먼트를 {id} / {int}로 치환하여 cardinality 폭발을 방지한다.
    """
    import re
    # UUID
    path = re.sub(
        r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "/{id}",
        path,
    )
    # 순수 숫자 세그먼트
    path = re.sub(r"/\d+", "/{int}", path)
    return path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """HTTP 요청당 메트릭을 기록한다."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        path = request.url.path

        if path in _SKIP_PATHS:
            return await call_next(request)

        normalized = _normalize_path(path)
        method = request.method
        start = time.monotonic()

        response = await call_next(request)

        elapsed = time.monotonic() - start
        status = str(response.status_code)

        metrics.HTTP_REQUESTS.labels(method=method, path=normalized, status=status).inc()
        metrics.HTTP_DURATION.labels(method=method, path=normalized).observe(elapsed)

        return response
