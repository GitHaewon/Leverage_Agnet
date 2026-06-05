"""
Risk Engine API 라우터.

엔드포인트:
  GET  /risk/status          — 현재 Risk 현황 + halt 상태
  POST /risk/validate        — 시그널 사전 검증 (주문 전 필수)
  POST /risk/kill-switch     — Kill Switch 활성화
  DELETE /risk/kill-switch   — Kill Switch 해제 (재활성화)
  POST /risk/emergency-stop  — 긴급 거래 중단
  POST /risk/global-kill-switch — 시스템 전체 중단 (관리자 전용)
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Body, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUserDep, DbDep, RedisDep
from app.schemas.common import DataResponse
from app.services.risk_service import RiskService
from agents.risk.models import RawSignal

router = APIRouter(prefix="/risk", tags=["risk"])


# ── Request / Response 스키마 ─────────────────────────────────────────────────

class SignalValidateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    direction: Literal["LONG", "SHORT", "HOLD"]
    coin: str
    symbol: str
    confidence: float
    entry_price: Decimal
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    leverage: int
    signal_id: str | None = None


class ValidationResultResponse(BaseModel):
    approved: bool
    rejection_reason: str | None
    rejection_code: str | None
    quantity: str | None
    final_leverage: int | None
    margin_required_usdt: str | None
    max_loss_usdt: str | None
    max_profit_usdt: str | None
    rr_ratio: str | None
    pre_action: str | None
    existing_position_id: str | None
    warnings: list[str]


class KillSwitchRequest(BaseModel):
    reason: str


class EmergencyStopRequest(BaseModel):
    reason: str


class GlobalKillSwitchRequest(BaseModel):
    reason: str
    admin_confirm: Literal["GLOBAL_HALT_CONFIRMED"]


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get(
    "/status",
    response_model=DataResponse[dict],
    summary="Risk 현황 조회 (Halt 상태, 손실 현황, 포지션 수)",
)
async def get_risk_status(
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[dict]:
    svc = RiskService(db=db, redis=redis)
    summary = await svc.get_risk_summary(current_user.id)
    return DataResponse(data=summary)


@router.post(
    "/validate",
    response_model=DataResponse[ValidationResultResponse],
    summary="시그널 Risk 검증 (주문 실행 전 필수)",
    description=(
        "Risk Engine이 승인하지 않은 시그널은 주문으로 실행할 수 없습니다.\n\n"
        "approved=false인 경우 rejection_code와 rejection_reason을 확인하세요."
    ),
)
async def validate_signal(
    body: SignalValidateRequest,
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[ValidationResultResponse]:
    signal = RawSignal(
        direction=body.direction,
        coin=body.coin,
        symbol=body.symbol,
        confidence=body.confidence,
        entry_price=body.entry_price,
        take_profit=body.take_profit,
        stop_loss=body.stop_loss,
        leverage=body.leverage,
        signal_id=uuid.UUID(body.signal_id) if body.signal_id else None,
    )
    svc = RiskService(db=db, redis=redis)
    result = await svc.validate_signal(current_user.id, signal)

    return DataResponse(
        data=ValidationResultResponse(
            approved=result.approved,
            rejection_reason=result.rejection_reason,
            rejection_code=result.rejection_code,
            quantity=str(result.quantity) if result.quantity is not None else None,
            final_leverage=result.final_leverage,
            margin_required_usdt=str(result.margin_required_usdt) if result.margin_required_usdt else None,
            max_loss_usdt=str(result.max_loss_usdt) if result.max_loss_usdt else None,
            max_profit_usdt=str(result.max_profit_usdt) if result.max_profit_usdt else None,
            rr_ratio=str(result.rr_ratio) if result.rr_ratio else None,
            pre_action=result.pre_action,
            existing_position_id=str(result.existing_position_id) if result.existing_position_id else None,
            warnings=result.warnings,
        )
    )


@router.post(
    "/kill-switch",
    response_model=DataResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="Kill Switch 활성화 (즉시 거래 중단)",
)
async def activate_kill_switch(
    body: KillSwitchRequest,
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[dict]:
    svc = RiskService(db=db, redis=redis)
    await svc.activate_kill_switch(current_user.id, body.reason)
    return DataResponse(data={
        "message": "Kill Switch 활성화됨. 자동매매가 즉시 중단되었습니다.",
        "reason": body.reason,
    })


@router.delete(
    "/kill-switch",
    response_model=DataResponse[dict],
    summary="Kill Switch 해제 (거래 재활성화)",
)
async def deactivate_kill_switch(
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[dict]:
    svc = RiskService(db=db, redis=redis)
    await svc.deactivate_kill_switch(current_user.id)
    return DataResponse(data={
        "message": "Kill Switch 해제됨. 자동매매 재활성화를 위해 설정에서 확인하세요."
    })


@router.post(
    "/emergency-stop",
    response_model=DataResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="긴급 거래 중단 (즉시 + 포지션 청산 권고)",
)
async def emergency_stop(
    body: EmergencyStopRequest,
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[dict]:
    svc = RiskService(db=db, redis=redis)
    await svc.activate_kill_switch(current_user.id, f"EMERGENCY: {body.reason}")
    return DataResponse(data={
        "message": "긴급 중단 활성화됨. 오픈 포지션을 즉시 확인하세요.",
        "reason": body.reason,
        "action_required": "기존 포지션은 자동 청산되지 않습니다. 수동으로 청산하거나 /closeall을 사용하세요.",
    })
