"""
Reflection API — /api/v1/reflections

엔드포인트:
  GET  /reflections                        목록 (페이지네이션)
  GET  /reflections/{position_id}          포지션별 회고 조회
  POST /reflections/{position_id}/trigger  수동 회고 생성 트리거
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.reflection import (
    ReflectionReportResponse,
    ReflectionTriggerRequest,
)
from app.services.reflection_service import ReflectionNotFoundError, ReflectionService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/reflections", tags=["reflections"])


def _get_service(db: AsyncSession = Depends(get_db)) -> ReflectionService:
    return ReflectionService(db)


# ── 목록 ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=dict[str, Any])
async def list_reflections(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: ReflectionService = Depends(_get_service),
) -> dict[str, Any]:
    return await service.list_reports(current_user.id, page=page, size=size)


# ── 포지션별 단건 조회 ─────────────────────────────────────────────────────────

@router.get("/{position_id}", response_model=ReflectionReportResponse)
async def get_reflection(
    position_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ReflectionService = Depends(_get_service),
) -> ReflectionReportResponse:
    try:
        return await service.get_by_position(position_id, current_user.id)
    except ReflectionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reflection not found for this position",
        )


# ── 수동 트리거 ───────────────────────────────────────────────────────────────

@router.post("/{position_id}/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_reflection(
    position_id: uuid.UUID,
    body: ReflectionTriggerRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """
    포지션에 대한 회고 분석을 Celery 태스크로 비동기 실행한다.
    실제 분석은 백그라운드에서 진행되며, 완료 후 GET으로 결과를 조회한다.
    포지션 데이터는 Celery 태스크 내부에서 DB로부터 직접 조회한다.
    """
    from app.workers.reflection_worker import trigger_reflection_for_position

    # 포지션 데이터를 DB에서 조회하여 태스크에 전달
    task = trigger_reflection_for_position.apply_async(
        kwargs={
            "position_id": str(position_id),
            "user_id": str(current_user.id),
            "journal_id": str(body.journal_id) if body.journal_id else None,
            "price_action_summary": body.price_action_summary,
            # 나머지 필드는 태스크 내부에서 DB 조회
            # 이 엔드포인트는 재실행(manual trigger) 용도 — 데이터는 DB에 있음
        },
        countdown=0,
    )

    return {
        "task_id": task.id,
        "status": "accepted",
        "message": "Reflection analysis started. Check GET /reflections/{position_id} for results.",
    }
