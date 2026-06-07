"""
Signal API — 수동 시그널 요청 엔드포인트.

클라이언트는 POST /api/v1/signals/run을 호출해 Celery 태스크를 enqueue하고
task_id를 받는다. GET /api/v1/signals/status/{task_id}로 결과를 폴링한다.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.models.user import User
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalRunRequest(BaseModel):
    coin: Literal["BTC", "ETH"]


class SignalRunResponse(BaseModel):
    task_id: str
    coin: str
    message: str = "분석 요청이 접수되었습니다."


class SignalStatusResponse(BaseModel):
    task_id: str
    state: str
    result: dict | None = None


@router.post("/run", response_model=SignalRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_signal(
    body: SignalRunRequest,
    current_user: User = Depends(get_current_user),
) -> SignalRunResponse:
    """
    특정 코인에 대해 AI 시그널 파이프라인을 즉시 실행한다.
    Celery 태스크로 비동기 처리되며 task_id를 반환한다.
    """
    task = celery_app.send_task(
        "app.workers.analysis_worker.run_signal_for_user",
        kwargs={
            "user_id": str(current_user.id),
            "coin": body.coin,
        },
    )
    return SignalRunResponse(task_id=task.id, coin=body.coin)


@router.get("/status/{task_id}", response_model=SignalStatusResponse)
async def get_signal_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> SignalStatusResponse:
    """
    Celery 태스크 상태 조회.
    state: PENDING | STARTED | SUCCESS | FAILURE | RETRY
    """
    result = celery_app.AsyncResult(task_id)
    payload: dict | None = None

    if result.state == "SUCCESS":
        payload = result.result
    elif result.state == "FAILURE":
        payload = {"error": str(result.result)}

    return SignalStatusResponse(task_id=task_id, state=result.state, result=payload)
