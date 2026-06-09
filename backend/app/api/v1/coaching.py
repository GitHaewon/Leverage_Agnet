"""
AI Trading Coach API.

GET  /coaching/reports         — 리포트 목록 (페이지네이션)
GET  /coaching/reports/latest  — 최신 리포트
POST /coaching/trigger         — 수동 분석 트리거 (202 Accepted)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.coaching import CoachingReportResponse, CoachingTriggerRequest
from app.services.coaching_service import CoachingNotFoundError, CoachingService

router = APIRouter(prefix="/coaching", tags=["coaching"])


@router.get("/reports", response_model=dict)
async def list_reports(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = CoachingService(db)
    return await service.list_reports(
        user_id=current_user.id, page=page, size=size
    )


@router.get("/reports/latest", response_model=CoachingReportResponse)
async def get_latest_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CoachingReportResponse:
    service = CoachingService(db)
    try:
        return await service.get_latest_report(user_id=current_user.id)
    except CoachingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="코칭 리포트가 없습니다. 거래 후 리포트가 생성됩니다.",
        )


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_coaching(
    body: CoachingTriggerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from app.workers.coaching_worker import run_coaching_for_user

    task = run_coaching_for_user.delay(
        user_id=str(current_user.id),
        period_days=body.period_days,
    )
    return {
        "message": "코칭 분석이 시작되었습니다.",
        "task_id": task.id,
        "period_days": body.period_days,
    }
