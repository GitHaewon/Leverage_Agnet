"""
Trading API — 자동매매 제어 엔드포인트.

레이어 규칙: Route는 요청 파싱과 응답 직렬화만 담당한다.
모든 비즈니스 로직은 TradingService에 위임한다.
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUserDep, RedisDep
from app.core.config import settings
from app.schemas.common import DataResponse
from app.schemas.trading import TradingResumeData
from app.services.trading_service import resume_auto_trading

router = APIRouter(prefix="/trading", tags=["trading"])
logger = logging.getLogger(__name__)


def _get_safety_gate(redis: aioredis.Redis) -> "SafetyGate":
    from app.safety import RedisSafetyStateStore, SafetyConfig, SafetyGate
    return SafetyGate(
        store=RedisSafetyStateStore(redis),
        config=SafetyConfig(live_trading_enabled=settings.LIVE_TRADING_ENABLED),
    )


@router.post(
    "/resume",
    response_model=DataResponse[TradingResumeData],
    status_code=status.HTTP_200_OK,
    summary="자동매매 재개",
    description=(
        "Kill switch 중단 기간이 만료된 후 자동매매를 재개한다. "
        "아직 중단 기간이 남아 있으면 409를 반환한다. "
        "본인 계정만 재개할 수 있다."
    ),
)
async def resume_trading(
    current_user: CurrentUserDep,
    redis: RedisDep,
) -> DataResponse[TradingResumeData]:
    gate = _get_safety_gate(redis)
    result = await resume_auto_trading(str(current_user.id), gate)
    return DataResponse(
        data=TradingResumeData(
            is_trading_active=result["is_trading_active"],
            resumed_at=result["resumed_at"],
            message=result["message"],
        )
    )
