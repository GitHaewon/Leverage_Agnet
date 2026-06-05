"""
Position Sizing API.

엔드포인트:
  POST /sizing/calculate   — 단일 방법으로 포지션 크기 계산
  POST /sizing/compare     — 4가지 방법 동시 비교
  GET  /sizing/kelly-stats — 현재 Kelly 통계 (승률, 평균 수익/손실)
"""
from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DbDep
from app.schemas.common import DataResponse
from app.schemas.sizing import (
    CompareRequest,
    CompareData,
    KellyStatsData,
    SizingData,
    SizingRequest,
)
from app.services.sizing_service import SizingService
from agents.risk.sizing_models import SizingMethod

router = APIRouter(prefix="/sizing", tags=["sizing"])
logger = logging.getLogger(__name__)


def _result_to_schema(result) -> SizingData:
    kelly_data = None
    if result.kelly:
        from app.schemas.sizing import KellyData
        kelly_data = KellyData(
            full_kelly=result.kelly.full_kelly_fraction,
            applied_fraction=result.kelly.applied_fraction,
            multiplier=result.kelly.kelly_multiplier,
            win_rate=f"{result.kelly.win_rate:.1%}",
            avg_odds=result.kelly.avg_odds,
            sample_size=result.kelly.sample_size,
            is_valid=result.kelly.is_valid,
            reason=result.kelly.reason,
        )
    return SizingData(
        method=result.method.value,
        risk_amount_usdt=str(result.risk_amount_usdt),
        risk_pct=f"{result.risk_pct:.2%}",
        quantity=str(result.quantity),
        margin_used=str(result.margin_used),
        position_value=str(result.position_value),
        max_loss=str(result.max_loss),
        max_profit=str(result.max_profit),
        final_leverage=result.final_leverage,
        rr_ratio=str(result.rr_ratio),
        kelly=kelly_data,
        warnings=result.warnings,
    )


@router.post(
    "/calculate",
    response_model=DataResponse[SizingData],
    summary="포지션 사이징 계산 (단일 방법)",
    description=(
        "지정된 방법으로 최적 포지션 크기를 계산합니다.\n\n"
        "**방법 설명:**\n"
        "- `fixed_risk`: 총 잔고의 N%를 손실 한도\n"
        "- `fixed_dollar`: 고정 USDT 금액을 손실 한도\n"
        "- `percent_risk`: 가용 잔고의 N%를 손실 한도\n"
        "- `kelly`: Kelly Criterion 최적 비율 (거래 이력 필요)"
    ),
)
async def calculate_sizing(
    body: SizingRequest,
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[SizingData]:
    svc = SizingService(db=db)
    result = await svc.calculate(
        user=current_user,
        method=SizingMethod(body.method),
        signal_params={
            "direction":   body.direction,
            "symbol":      body.symbol,
            "entry_price": str(body.entry_price),
            "stop_loss":   str(body.stop_loss),
            "take_profit": str(body.take_profit) if body.take_profit else None,
            "leverage":    body.leverage,
        },
        risk_pct=body.risk_pct,
        risk_usdt=body.risk_usdt,
        kelly_fraction=body.kelly_fraction,
        kelly_lookback_days=body.kelly_lookback_days,
    )
    return DataResponse(data=_result_to_schema(result))


@router.post(
    "/compare",
    response_model=DataResponse[CompareData],
    summary="4가지 사이징 방법 비교",
    description=(
        "Fixed Risk, Fixed Dollar, Percent Risk, Kelly 방법을 "
        "동일 조건으로 계산해 비교 테이블을 반환합니다."
    ),
)
async def compare_sizing(
    body: CompareRequest,
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[CompareData]:
    svc = SizingService(db=db)
    comparison = await svc.compare_all(
        user=current_user,
        signal_params={
            "direction":   body.direction,
            "symbol":      body.symbol,
            "entry_price": str(body.entry_price),
            "stop_loss":   str(body.stop_loss),
            "take_profit": str(body.take_profit) if body.take_profit else None,
            "leverage":    body.leverage,
        },
        base_risk_pct=body.base_risk_pct,
        kelly_fraction=body.kelly_fraction,
        kelly_lookback_days=body.kelly_lookback_days,
    )
    return DataResponse(data=CompareData(**comparison.summary()))


@router.get(
    "/kelly-stats",
    response_model=DataResponse[dict],
    summary="Kelly Criterion 분석 (승률 + 최적 비율)",
    description=(
        "최근 N일간 거래 이력을 분석해 Kelly Criterion 적용 결과를 반환합니다.\n\n"
        "Kelly 방법을 사용하기 전 현재 전략의 기대값을 확인하세요."
    ),
)
async def get_kelly_stats(
    current_user: CurrentUserDep,
    db: DbDep,
    kelly_fraction: float = Query(default=0.25, ge=0.1, le=1.0),
    lookback_days: int = Query(default=90, ge=7, le=365),
) -> DataResponse[dict]:
    svc = SizingService(db=db)
    stats = await svc.get_kelly_stats(
        user=current_user,
        kelly_fraction=kelly_fraction,
        lookback_days=lookback_days,
    )
    return DataResponse(data=stats)
