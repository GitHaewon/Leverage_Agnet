"""
Prometheus 스크레이핑 엔드포인트.

경로: GET /metrics
Prometheus 서버는 이 경로를 30초마다 스크레이핑한다.
인증 없음 — 내부 네트워크에서만 접근 가능하도록 Nginx로 제어한다.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["observability"])


@router.get(
    "/metrics",
    response_class=Response,
    summary="Prometheus 메트릭 스크레이핑 엔드포인트",
    include_in_schema=False,
)
def prometheus_metrics() -> Response:
    """
    모든 Prometheus 메트릭을 text/plain 포맷으로 반환한다.
    Prometheus scrape_config에서 job: trading-copilot-backend 로 수집한다.
    """
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
